import os
import glob
import random
import asyncio
import tempfile
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

from PIL import Image, ImageDraw, ImageFont, features
from gtts import gTTS
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("BOT_TOKEN environment variable সেট করা নেই")

W, H = 540, 960          # ছোট সাইজ = ফ্রি সার্ভারে দ্রুত হয়
MAX_BG_MB = 20           # বট ২০MB পর্যন্ত ফাইল ডাউনলোড করতে পারে
MAX_CHARS = 300          # লেখা বেশি বড় হলে ফ্রি সার্ভারে ভিডিও বানাতে দেরি হয়
COLORS = ["0x1a1a2e", "0x16213e", "0x0f3460", "0x2d132c", "0x1b4332", "0x3c096c", "0x5f0f40"]
LOCK = asyncio.Semaphore(1)  # একসাথে একটাই ভিডিও বানাবে (মেমরি বাঁচাতে)

RAQM = features.check("raqm")
if not RAQM:
    print("⚠️ raqm নেই, বাংলা যুক্তাক্ষর ভেঙে যেতে পারে")


def find_font():
    patterns = [
        "/usr/share/fonts/**/NotoSansBengali*.ttf",
        "/usr/share/fonts/**/*Bengali*.ttf",
        "/usr/share/fonts/**/*Mukti*.ttf",
        "/usr/share/fonts/**/*Beng*.ttf",
    ]
    for p in patterns:
        found = glob.glob(p, recursive=True)
        if found:
            found.sort(key=lambda x: ("Regular" not in x and "VF" not in x, x))
            return found[0]
    raise SystemExit("বাংলা ফন্ট পাওয়া যায়নি")


FONT = find_font()
print("Font:", FONT, "| raqm:", RAQM)


def wrap(draw, text, font, max_w):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if draw.textlength(test, font=font) <= max_w:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def make_text_png(text, path):
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    engine = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
    max_w = W - 100
    area_h = H - 300

    for size in range(60, 27, -4):
        font = ImageFont.truetype(FONT, size, layout_engine=engine)
        lines = wrap(probe, text, font, max_w)
        line_h = int(size * 1.6)
        if line_h * len(lines) <= area_h:
            break

    max_lines = max(1, area_h // line_h)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] += "…"

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    total = line_h * len(lines)
    y0 = (H - total) // 2
    pad = 28
    d.rounded_rectangle((30, y0 - pad, W - 30, y0 + total + pad), radius=28, fill=(0, 0, 0, 120))
    y = y0
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((W - w) / 2, y), ln, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += line_h
    img.save(path)


def make_voice(text, path):
    # Google এর ফ্রি বাংলা ভয়েস (চালানোর সময় ইন্টারনেট লাগে, Render এ আছে)
    gTTS(text=text, lang="bn").save(path)


def audio_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def build_video(text, bg_path, out_path, tmp):
    png = os.path.join(tmp, "text.png")
    make_text_png(text, png)

    voice = os.path.join(tmp, "voice.mp3")
    make_voice(text, voice)
    dur = f"{audio_duration(voice) + 1.0:.2f}"   # ভয়েসের পর ১ সেকেন্ড বাড়তি

    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]

    if bg_path:
        cmd = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", bg_path,
            "-loop", "1", "-t", dur, "-i", png, "-i", voice,
            "-filter_complex",
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=25[bg];"
            "[1:v]format=rgba,fade=t=in:st=0:d=0.8:alpha=1[t];"
            "[bg][t]overlay=0:0:shortest=1,format=yuv420p[v]",
            "-map", "[v]", "-map", "2:a", "-t", dur, *enc, out_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={random.choice(COLORS)}:s={W}x{H}:d={dur}:r=25",
            "-loop", "1", "-t", dur, "-i", png, "-i", voice,
            "-filter_complex",
            "[1:v]format=rgba,fade=t=in:st=0:d=0.8:alpha=1[t];"
            "[0:v][t]overlay=0:0:shortest=1,format=yuv420p[v]",
            "-map", "[v]", "-map", "2:a", "-t", dur, *enc, out_path,
        ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


def bg_path_for(uid):
    return os.path.join(tempfile.gettempdir(), f"bg_{uid}.mp4")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 স্বাগতম!\n\n"
        "✍️ বাংলায় যা খুশি লিখে পাঠান, আমি সেটা বাংলা ভয়েসে পড়ে শুনিয়ে ভিডিও বানিয়ে দেব।\n"
        "🎬 আগে একটা ভিডিও পাঠালে সেটাই ব্যাকগ্রাউন্ড হবে (২০MB এর মধ্যে)।\n"
        "♻️ /reset দিলে ব্যাকগ্রাউন্ড ভিডিও মুছে যাবে।"
    )


async def reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    p = bg_path_for(update.message.from_user.id)
    if os.path.exists(p):
        os.remove(p)
    await update.message.reply_text("✅ ব্যাকগ্রাউন্ড ভিডিও মুছে ফেলেছি।")


async def on_video(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media = msg.video or msg.animation
    if media.file_size and media.file_size > MAX_BG_MB * 1024 * 1024:
        await msg.reply_text("❌ ভিডিও ২০MB এর বেশি। ছোট ভিডিও দিন।")
        return
    try:
        f = await media.get_file()
        await f.download_to_drive(bg_path_for(msg.from_user.id))
        await msg.reply_text("✅ ভিডিও সেভ হয়েছে! এখন বাংলা লেখা পাঠান।")
    except Exception as e:
        print("download error:", e)
        await msg.reply_text("❌ ভিডিও নামাতে পারিনি, আবার চেষ্টা করুন।")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = (msg.text or "").strip()
    if not text:
        return
    if len(text) > MAX_CHARS:
        await msg.reply_text(f"❌ লেখা অনেক বড়। {MAX_CHARS} অক্ষরের মধ্যে লিখুন (এখন {len(text)})।")
        return
    wait = await msg.reply_text("⏳ ভয়েস আর ভিডিও বানাচ্ছি...")
    bg = bg_path_for(msg.from_user.id)
    bg = bg if os.path.exists(bg) else None

    async with LOCK:
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out.mp4")
            try:
                await asyncio.to_thread(build_video, text, bg, out, tmp)
                with open(out, "rb") as f:
                    await msg.reply_video(
                        video=f, width=W, height=H, supports_streaming=True,
                        read_timeout=120, write_timeout=120,
                    )
            except subprocess.CalledProcessError as e:
                print("ffmpeg error:", e.stderr.decode(errors="ignore")[-600:])
                await msg.reply_text("❌ ভিডিও বানাতে সমস্যা হয়েছে।")
            except Exception as e:
                print("error:", e)
                await msg.reply_text("❌ কিছু একটা সমস্যা হয়েছে, আবার চেষ্টা করুন।")
    try:
        await wait.delete()
    except Exception:
        pass


# Render ফ্রি Web Service এর জন্য ছোট্ট health সার্ভার
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def run_health():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "10000"))), Health).serve_forever()


def main():
    threading.Thread(target=run_health, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.VIDEO | filters.ANIMATION, on_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

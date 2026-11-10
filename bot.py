import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont, features
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

# ---------------------------------------------------------------- Settings
# Render-এ BOT_TOKEN environment variable দিলে সেটাই ব্যবহার হবে, না দিলে নিচের টোকেন।
# ⚠️ GitHub রিপো অবশ্যই Private রাখুন, নাহলে টোকেন চুরি হতে পারে।
TOKEN = os.environ.get(
    "BOT_TOKEN", "8952937185:AAGXH7Pp1fmENqfY-y_IExxSsfxcu4GDhnM"
).strip()
if not TOKEN:
    raise SystemExit("বটের টোকেন পাওয়া যায়নি।")

MAX_CHARS = 1000
W, H = 720, 1280          # ভিডিওর সাইজ (ভার্টিক্যাল)
MARGIN = 60
JOBS = asyncio.Semaphore(2)  # একসাথে সর্বোচ্চ ২টি ভিডিও (Render-এর কম RAM-এর জন্য)

TEXT_COLOR = (0, 255, 204)
SHADOW_COLOR = (0, 0, 0)
BG_TOP = (10, 10, 30)
BG_BOTTOM = (40, 10, 60)


# ---------------------------------------------------------------- Font
def find_bengali_font():
    """বাংলা সাপোর্ট করে এমন ফন্ট খুঁজে বের করে।"""
    candidates = [
        os.environ.get("FONT_PATH"),
        os.path.join(os.path.dirname(__file__), "fonts", "NotoSansBengali-Bold.ttf"),
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    try:
        out = subprocess.check_output(
            ["fc-list", ":lang=bn", "file"], text=True, timeout=10
        )
        paths = [l.split(":")[0].strip() for l in out.splitlines() if l.strip()]
        paths = [p for p in paths if os.path.exists(p)]
        paths.sort(key=lambda p: ("Bold" not in p, not p.lower().endswith(".ttf")))
        if paths:
            return paths[0]
    except Exception as e:
        log.warning("fc-list চালানো যায়নি: %s", e)
    return None


FONT_PATH = find_bengali_font()
HAS_RAQM = features.check("raqm")
log.info("Font: %s | raqm: %s", FONT_PATH, HAS_RAQM)
if not FONT_PATH:
    log.warning("বাংলা ফন্ট পাওয়া যায়নি — লেখা ভুলভাবে দেখাবে!")
if not HAS_RAQM:
    log.warning("raqm নেই — বাংলা যুক্তাক্ষর ভেঙে যাবে (libraqm/libfribidi ইনস্টল করুন)!")


def load_font(size):
    if not FONT_PATH:
        return ImageFont.load_default()
    layout = ImageFont.Layout.RAQM if HAS_RAQM else ImageFont.Layout.BASIC
    return ImageFont.truetype(FONT_PATH, size, layout_engine=layout)


# ---------------------------------------------------------------- Image
def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=color)
    return img


def wrap_text(draw, text, font, max_w):
    """পিক্সেল-প্রস্থ ধরে লাইন ভাঙে; নতুন লাইন (Enter) বজায় রাখে।"""
    lines = []
    for para in text.splitlines():
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            test = f"{cur} {word}" if cur else word
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def render_text_image(text, path):
    img = gradient(W, H, BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    max_w = W - 2 * MARGIN
    max_h = H - 2 * 170

    # লেখা বড় হলে ফন্ট ছোট করে ফিট করানো হয়
    for size in range(60, 23, -4):
        font = load_font(size)
        line_h = int(size * 1.6)
        lines = wrap_text(draw, text, font, max_w)
        widest = max((draw.textlength(l, font=font) for l in lines), default=0)
        if len(lines) * line_h <= max_h and widest <= max_w:
            break
    else:
        lines = lines[: max_h // line_h]

    # উপরের সাজানো দাগ
    draw.rounded_rectangle(
        [(W // 2 - 60, 110), (W // 2 + 60, 118)], radius=4, fill=TEXT_COLOR
    )

    y = (H - len(lines) * line_h) // 2
    for line in lines:
        if line:
            w = draw.textlength(line, font=font)
            x = (W - w) / 2
            draw.text((x + 3, y + 3), line, font=font, fill=SHADOW_COLOR)
            draw.text((x, y), line, font=font, fill=TEXT_COLOR)
        y += line_h

    img.save(path)


# ---------------------------------------------------------------- Audio / Video
def make_audio(text, path):
    gTTS(text=text, lang="bn").save(path)


async def run_ffmpeg(image_path, audio_path, output_path):
    args = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", "2", "-i", image_path,
        "-i", audio_path,
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
        "-r", "10",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffmpeg timeout")
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="ignore")[-500:])


# ---------------------------------------------------------------- Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "হ্যালো! আমাকে যেকোনো বাংলা লেখা পাঠান, আমি সেটিকে স্টাইলিশ ফন্ট ও ভয়েস সহ "
        "সুন্দর ভিডিওতে রূপান্তর করে দেবো! 🎬✨"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    if len(text) > MAX_CHARS:
        await update.message.reply_text(
            f"⚠️ দয়া করে {MAX_CHARS} অক্ষরের মধ্যে ছোট লেখা পাঠান যাতে দ্রুত ভিডিও তৈরি হতে পারে।"
        )
        return

    status = await update.message.reply_text(
        "⏳ আপনার স্টাইলিশ ভিডিও তৈরি হচ্ছে, একটু অপেক্ষা করুন..."
    )

    # প্রতিটি রিকোয়েস্টের জন্য আলাদা ফোল্ডার — একাধিক ইউজারের ফাইল মিশে যাবে না
    workdir = tempfile.mkdtemp(prefix="vid_")
    audio_path = os.path.join(workdir, "audio.mp3")
    image_path = os.path.join(workdir, "text.png")
    video_path = os.path.join(workdir, "output.mp4")

    try:
        async with JOBS:
            await asyncio.to_thread(make_audio, text, audio_path)
            await asyncio.to_thread(render_text_image, text, image_path)
            await run_ffmpeg(image_path, audio_path, video_path)

        await context.bot.send_chat_action(update.effective_chat.id, "upload_video")
        with open(video_path, "rb") as f:
            await update.message.reply_video(
                video=f,
                caption="✨ আপনার প্রিমিয়াম স্টাইলিশ ভিডিও প্রস্তুত!",
                width=W,
                height=H,
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30,
            )
        await status.delete()

    except Exception:
        log.exception("ভিডিও তৈরিতে সমস্যা")
        try:
            await status.edit_text(
                "দুঃখিত, ভিডিও তৈরি করতে সমস্যা হয়েছে। একটু পরে আবার চেষ্টা করুন।"
            )
        except Exception:
            pass
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


# ---------------------------------------------------------------- Health server (Render)
class Health(BaseHTTPRequestHandler):
    def _ok(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        self._ok()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self._ok()

    def log_message(self, *args):
        pass


def run_health():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()


def main():
    threading.Thread(target=run_health, daemon=True).start()

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app.add_error_handler(on_error)

    print("Bot is running smoothly...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

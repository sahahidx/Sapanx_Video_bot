"""Sapanx Video Bot: লেখা পাঠালে কার্টুন ভিডিও বানায়। actions.py এটা ব্যবহার করে।"""
import array
import asyncio
import glob
import logging
import math
import os
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer

from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import actions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

TOKEN = os.environ.get("BOT_TOKEN", "")
FPS = 12
SUB_SIZE = 38
SUB_MAX_W = 440
SUB_LINES = 3
MAX_RENDER_SECONDS = 150
MAX_CHARS = 250
SKIN = (255, 214, 170)
HAIR = (50, 35, 30)
DARK = (40, 30, 30)


# ---------- ফন্ট ও সাবটাইটেল ----------
@lru_cache(maxsize=None)
def load_font(size):
    paths = [os.environ.get("FONT_PATH", ""),
             "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
             "/usr/share/fonts/truetype/lohit-bengali/Lohit-Bengali.ttf"]
    paths += glob.glob("/usr/share/fonts/**/*engali*.ttf", recursive=True)
    paths += glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "*.ttf"))
    for p in paths:
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, layout_engine=ImageFont.Layout.RAQM)
            except Exception:
                return ImageFont.truetype(p, size)
    raise RuntimeError("বাংলা ফন্ট পাওয়া যায়নি (Dockerfile-এ fonts-noto-core দিন)")


def wrap_text(draw, text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def split_subtitles(text, font, max_w, max_lines):
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    chunks, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if len(wrap_text(d, trial, font, max_w)) <= max_lines or not cur:
            cur = trial
        else:
            chunks.append(cur)
            cur = w
    if cur:
        chunks.append(cur)
    return chunks or [text]


def draw_subtitle(img, lines, font):
    d = ImageDraw.Draw(img)
    lh = int(SUB_SIZE * 1.5)
    top, bottom = actions.PANEL_Y, actions.PANEL_Y + 225
    y = top + (bottom - top - lh * len(lines)) // 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text(((actions.FW - w) / 2, y), ln, font=font, fill="white")
        y += lh


# ---------- অডিও ----------
def mouth_levels(wav_path, fps):
    with wave.open(wav_path, "rb") as wf:
        sr, n = wf.getframerate(), wf.getnframes()
        samples = array.array("h", wf.readframes(n))
    if not samples:
        return [], 0.0
    duration = len(samples) / sr
    step = max(1, int(sr / fps))
    rms = []
    for i in range(0, len(samples), step):
        seg = samples[i:i + step]
        rms.append(math.sqrt(sum(x * x for x in seg) / len(seg)))
    ref = sorted(rms)[int(len(rms) * 0.95)] or 1.0
    levels, prev = [], 0.0
    for r in rms:
        v = min(1.0, r / ref)
        prev = prev * 0.4 + v * 0.6
        levels.append(prev)
    return levels, duration


def mouth_state(lv):
    return 0 if lv < 0.12 else 1 if lv < 0.4 else 2 if lv < 0.7 else 3


def make_audio(text, wav_path):
    mp3 = wav_path + ".mp3"
    gTTS(text=text, lang="bn").save(mp3)
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", "16000", wav_path],
                       capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="ignore")[-300:])


# ---------- মাথা ----------
@lru_cache(maxsize=None)
def head_sprite(m, b):
    im = Image.new("RGBA", (330, 364), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([8, 8, 322, 260], fill=HAIR)
    d.ellipse([10, 190, 42, 252], fill=SKIN)
    d.ellipse([288, 190, 320, 252], fill=SKIN)
    d.ellipse([22, 60, 308, 352], fill=SKIN)
    d.chord([22, 60, 308, 230], 180, 360, fill=HAIR)
    d.ellipse([50, 240, 100, 275], fill=(255, 170, 160))
    d.ellipse([230, 240, 280, 275], fill=(255, 170, 160))
    for cx in (118, 212):
        y = 200
        if b:
            d.arc([cx - 22, y - 14, cx + 22, y + 14], 200, 340, fill=DARK, width=7)
        else:
            d.ellipse([cx - 24, y - 28, cx + 24, y + 28], fill="white")
            d.ellipse([cx - 12, y - 14, cx + 12, y + 14], fill=DARK)
            d.ellipse([cx - 6, y - 12, cx + 2, y - 4], fill="white")
    d.arc([150, 228, 180, 250], 20, 160, fill=(200, 150, 120), width=4)
    if m == 0:
        d.arc([135, 262, 195, 296], 20, 160, fill=DARK, width=6)
    elif m == 1:
        d.ellipse([148, 275, 182, 297], fill=(150, 40, 50))
    elif m == 2:
        d.ellipse([140, 270, 190, 306], fill=(150, 40, 50))
    else:
        d.ellipse([125, 265, 205, 322], fill=(150, 40, 50))
        d.ellipse([145, 298, 185, 320], fill=(240, 110, 120))
    return im


# ---------- ভিডিও বানানো ----------
def build_video(text, out_path):
    import sys
    me = sys.modules[__name__]
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "a.wav")
        make_audio(text, wav)
        actions.make_action_video(me, text, wav, out_path)


# ---------- ওয়েব সার্ভার (Render Free Web Service-এর জন্য) ----------
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


def keep_alive():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 10000))), Health).serve_forever()


# ---------- টেলিগ্রাম ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "হ্যালো! বাংলায় একটা বাক্য লিখে পাঠান, আমি কার্টুন ভিডিও বানিয়ে দেব।\n"
        "যেমন: \"সকালে সে দৌড়ে স্কুলে গেল\" বা \"রাতে বৃষ্টি পড়ছে, সে নাচছে\"।")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_CHARS:
        await update.message.reply_text(f"লেখা বেশি বড়। {MAX_CHARS} অক্ষরের মধ্যে লিখুন।")
        return
    wait = await update.message.reply_text("ভিডিও বানাচ্ছি, একটু অপেক্ষা করুন...")
    out = os.path.join(tempfile.gettempdir(), f"v_{update.message.message_id}_{update.effective_chat.id}.mp4")
    try:
        await asyncio.to_thread(build_video, text, out)
        with open(out, "rb") as f:
            await update.message.reply_video(f, width=actions.FW, height=actions.FH, supports_streaming=True,
                                             read_timeout=120, write_timeout=120)
    except Exception as e:
        log.exception("fail")
        await update.message.reply_text(f"ভিডিও বানানো গেল না: {str(e)[:200]}")
    finally:
        for p in (out, out + ".log"):
            if os.path.exists(p):
                os.remove(p)
        try:
            await wait.delete()
        except Exception:
            pass


def main():
    if not TOKEN:
        raise SystemExit("BOT_TOKEN সেট করা নেই")
    threading.Thread(target=keep_alive, daemon=True).start()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

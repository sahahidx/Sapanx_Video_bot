import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
TOKEN = "8952937185:AAF0qjCMokwh43ag7PE0er409ATwpOzOwf0"

# Health check server for Render 24/7 uptime
class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

def run_health():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Health)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("X sapan ")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    if len(text) > 1000:
        await update.message.reply_text("⚠️ দয়া করে ১০০০ অক্ষরের মধ্যে ছোট লেখা পাঠান যাতে দ্রুত ভিডিও তৈরি হতে পারে।")
        return

    msg = await update.message.reply_text("⏳ crating now ...")

    try:
        # 1. Generate Audio using gTTS
        audio_path = "audio.mp3"
        tts = gTTS(text=text, lang='bn')
        tts.save(audio_path)

        # Get audio duration using ffprobe
        probe_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {audio_path}"
        duration = float(subprocess.check_output(probe_cmd, shell=True).decode().strip())
        if duration < 1:
            duration = 3.0

        # 2. Create Stylish Text Image using Pillow
        img_width, img_height = 720, 1280  # Optimized resolution for fast rendering
        img = Image.new("RGB", (img_width, img_height), color=(10, 10, 18))
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 45)
        except:
            font = ImageFont.load_default()

        # Text wrapping
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if len(test_line) > 22:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)

        # Draw text centered with stylish effects
        line_height = 60
        total_text_height = len(lines) * line_height
        y_offset = max(100, (img_height - total_text_height) // 2)

        for line in lines:
            if y_offset > img_height - 100:
                break
            
            x = 60
            draw.text((x + 2, y_offset + 2), line, font=font, fill=(0, 0, 0))
            draw.text((x, y_offset), line, font=font, fill=(0, 255, 204))
            y_offset += line_height

        image_path = "text_image.png"
        img.save(image_path)

        # 3. Fast FFmpeg Video Generation
        output_video = "output.mp4"
        ffmpeg_cmd = f"ffmpeg -loop 1 -i {image_path} -i {audio_path} -c:v libx264 -preset ultrafast -tune stillimage -c:a aac -b:a 128k -t {duration} -pix_fmt yuv420p -shortest -y {output_video}"
        subprocess.run(ffmpeg_cmd, shell=True, check=True)

        # 4. Send Video to User
        with open(output_video, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="✨ আপনার প্রিমিয়াম স্টাইলিশ ভিডিও প্রস্তুত!")

        await msg.delete()

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text(f"checking for internet connection : {e}")

def main():
    import threading
    t = threading.Thread(target=run_health, daemon=True)
    t.start()

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running smoothly...")
    app.run_polling()

if __name__ == '__main__':
    main()

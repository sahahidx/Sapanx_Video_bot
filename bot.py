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
    await update.message.reply_text("হ্যালো! আমাকে যেকোনো বাংলা লেখা পাঠান, আমি সেটিকে স্টাইলিশ ফন্ট ও ভয়েস সহ সুন্দর ভিডিওতে রূপান্তর করে দেবো! 🎬✨")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text:
        return

    msg = await update.message.reply_text("⏳ আপনার স্টাইলিশ ভিডিও তৈরি হচ্ছে, একটু অপেক্ষা করুন...")

    try:
        # 1. Generate Audio using gTTS
        tts = gTTS(text=text, lang='bn')
        audio_path = "audio.mp3"
        tts.save(audio_path)

        # Get audio duration using ffprobe
        probe_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {audio_path}"
        duration = float(subprocess.check_output(probe_cmd, shell=True).decode().strip())
        if duration < 1:
            duration = 3.0

        # 2. Create Stylish Text Image (Motion/Style Font Look)
        img_width, img_height = 1080, 1920
        img = Image.new("RGB", (img_width, img_height), color=(15, 15, 25)) # Dark stylish background
        draw = ImageDraw.Draw(img)

        # Try loading a bold font, fallback to default if not available
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 65)
        except:
            font = ImageFont.load_default()

        # Text wrapping for stylish layout
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            # Approximate width check
            if len(test_line) > 22:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line
        if current_line:
            lines.append(current_line)

        # Draw stylish gradient boxes and text
        y_offset = (img_height - (len(lines) * 90)) // 2
        for line in lines:
            # Draw a subtle background card for text to give a pro motion graphics look
            bbox = font.getbbox(line)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            x = (img_width - w) // 2
            
            # Stylish glowing shadow effect
            draw.text((x + 4, y_offset + 4), line, font=font, fill=(0, 0, 0))
            # Main text with bright accent color
            draw.text((x, y_offset), line, font=font, fill=(0, 255, 204)) 
            y_offset += 90

        image_path = "text_image.png"
        img.save(image_path)

        # 3. Create Video using FFmpeg (Combining image and audio with smooth styling)
        output_video = "output.mp4"
        ffmpeg_cmd = f"ffmpeg -loop 1 -i {image_path} -i {audio_path} -c:v libx264 -tune stillimage -c:a aac -b:a 192k -t {duration} -pix_fmt yuv420p -shortest -y {output_video}"
        subprocess.run(ffmpeg_cmd, shell=True, check=True)

        # 4. Send Video to User
        with open(output_video, 'rb') as video_file:
            await update.message.reply_video(video=video_file, caption="✨ আপনার স্টাইলিশ ভিডিও প্রস্তুত!")

        await msg.delete()

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text(f"দুঃখিত, ভিডিও তৈরি করতে সমস্যা হয়েছে: {e}")

def main():
    # Start health check server in background thread
    import threading
    t = threading.Thread(target=run_health, daemon=True)
    t.start()

    # Start Telegram Bot
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()

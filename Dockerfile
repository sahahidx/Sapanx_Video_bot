FROM python:3.10-slim

# System dependencies ইনস্টল করা (FFmpeg সহ)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# পাইথন প্যাকেজগুলো ইনস্টল করা
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# প্রজেক্টের সব ফাইল কপি করা
COPY . .

# বট রান করার কমান্ড (আপনার মূল ফাইলের নাম যদি bot.py হয়)
CMD ["python", "bot.py"]

FROM python:3.10-slim

# সিস্টেম ডিপেন্ডেন্সি (FFmpeg এবং প্রয়োজনীয় লাইব্রেরি) ইনস্টল করা
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# কাজের ফোল্ডার নির্ধারণ করা
WORKDIR /app

# requirements.txt কপি করে পাইথন প্যাকেজগুলো ইনস্টল করা
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# প্রজেক্টের বাকি সব ফাইল কপি করা
COPY . .

# বট রান করার কমান্ড
CMD ["python", "bot.py"]

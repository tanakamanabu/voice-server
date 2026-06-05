FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    python3-dev \
    libopenblas-dev \
    espeak-ng \
    curl \
    unzip

# Vosk 日本語モデル
RUN curl -LsSf https://alphacephei.com/vosk/models/vosk-model-ja-0.22.zip -o vosk-model.zip && \
    unzip vosk-model.zip && \
    rm vosk-model.zip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]

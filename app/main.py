from flask import Flask, request, send_file
from faster_whisper import WhisperModel
import requests
import tempfile
import time
import subprocess

app = Flask(__name__)
model = WhisperModel("small", compute_type="int8", cpu_threads=2)

def tts(text):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    subprocess.run([
        "nice", "-n", "5",
        "espeak-ng",
        "-v", "ja",
        "-s", "170",   # スピード（調整可）
        "-w", tmp.name,
        text
    ])
    return tmp.name

@app.route("/voice", methods=["POST"])
def voice():
    start = time.time()
    file = request.files["file"]

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        file.save(tmp.name)
        t1 = time.time()
        print(f"保存まで: {t1 - start:.2f}s")

        segments, _ = model.transcribe(
            tmp.name,
            language="ja",
            vad_filter=True,
        )

        t2 = time.time()
        print(f"Whisper: {t2 - t1:.2f}s")

        text = "".join([seg.text for seg in segments])

    print("認識:", text)

    # 仮の応答（ここは後でAI化）
    response_text = f"{text} と言いましたね"

    wav_path = tts(response_text)

    t3 = time.time()
    
    print(f"speak-ng: {t3 - t2:.2f}s")

    print(f"合計: {t3 - start:.2f}s")

    return send_file(wav_path, mimetype="audio/wav")

app.run(host="0.0.0.0", port=8000)

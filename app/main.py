import os
import subprocess
import tempfile
import time

from faster_whisper import WhisperModel
from flask import Flask, request, send_file

from command_executor import execute
from vosk_detector import detect_commands

app = Flask(__name__)
whisper = WhisperModel("small", compute_type="int8", cpu_threads=2)


def tts(text):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    subprocess.run([
        "nice", "-n", "5",
        "espeak-ng", "-v", "ja", "-s", "170",
        "-w", tmp.name, text,
    ])
    return tmp.name


@app.route("/voice", methods=["POST"])
def voice():
    start = time.time()
    audio = request.files["file"]

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()
    audio.save(tmp_path)
    t1 = time.time()
    print(f"保存まで: {t1 - start:.2f}s")

    try:
        commands = detect_commands(tmp_path)
        t2 = time.time()
        print(f"Vosk: {t2 - t1:.2f}s")

        if commands:
            responses = [execute(cmd) for cmd in commands]
            response_text = "。".join(responses)
        else:
            segments, _ = whisper.transcribe(tmp_path, language="ja", vad_filter=True)
            t_w = time.time()
            print(f"Whisper: {t_w - t2:.2f}s")
            text = "".join(seg.text for seg in segments)
            print(f"認識: {text}")
            response_text = f"{text} と言いましたね"
    finally:
        os.unlink(tmp_path)

    wav_path = tts(response_text)
    print(f"合計: {time.time() - start:.2f}s")
    return send_file(wav_path, mimetype="audio/wav")


app.run(host="0.0.0.0", port=8000)

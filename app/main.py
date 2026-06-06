import logging
import os
import time

from faster_whisper import WhisperModel
from flask import Flask, jsonify, request, send_file

import database
import vosk_detector
from admin import admin as admin_blueprint
from command_executor import execute

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
app.register_blueprint(admin_blueprint)

# 起動時初期化
database.init_db()
vosk_detector.reload_grammar()

whisper = WhisperModel("small", compute_type="int8", cpu_threads=2)


@app.route("/voice", methods=["POST"])
def voice():
    start = time.time()
    audio = request.files["file"]

    tmp_path = f"/tmp/voice_{os.getpid()}_{int(start * 1000)}.wav"
    audio.save(tmp_path)
    t1 = time.time()
    logger.info("保存まで: %.2fs", t1 - start)

    try:
        commands = vosk_detector.detect_commands(tmp_path)
        t2 = time.time()
        logger.info("Vosk: %.2fs", t2 - t1)

        wav_path: str | None = None

        if commands:
            # 全コマンドのHA呼び出しを実行し、最初のコマンドの応答WAVを使う
            for i, cmd_name in enumerate(commands):
                result = execute(cmd_name)
                if i == 0:
                    wav_path = result
        else:
            # Whisper でログ用に文字起こし（応答には使わない）
            segments, _ = whisper.transcribe(tmp_path, language="ja", vad_filter=True)
            t_w = time.time()
            logger.info("Whisper: %.2fs", t_w - t2)
            text = "".join(seg.text for seg in segments)
            logger.info("Whisper 認識: %s", text or "(なし)")

            # フォールバック応答WAVをランダム選択
            fallback = database.get_random_fallback()
            if fallback:
                wav_path = fallback["wav_path"]
            else:
                logger.warning("有効なフォールバック応答WAVがありません。管理画面で生成してください。")

    finally:
        os.unlink(tmp_path)

    logger.info("合計: %.2fs", time.time() - start)

    if wav_path is None:
        return jsonify({"error": "応答WAVが未生成です。管理画面でWAVを生成してください。"}), 500

    return send_file(wav_path, mimetype="audio/wav")


@app.route("/reload", methods=["POST"])
def reload_grammar():
    """管理画面の「VOSKに反映」ボタンから呼ばれるエンドポイント。"""
    vosk_detector.reload_grammar()
    return jsonify({"status": "ok"})


app.run(host="0.0.0.0", port=8000)

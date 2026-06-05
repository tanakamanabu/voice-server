import json
import os
import wave
from vosk import KaldiRecognizer, Model

VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-ja-0.22")

COMMANDS = {
    "ライトオン":    "ライト オン",
    "ライトオフ":    "ライト オフ",
    "冷房オン":      "冷房 オン",
    "暖房オン":      "暖房 オン",
    "エアコンオフ":  "エアコン オフ",
    "学習開始":      "学習 開始",
    "パソコンつけて": "パソコン つけて",
}

VOSK_GRAMMAR = json.dumps(list(COMMANDS.values()) + ["[unk]"], ensure_ascii=False)

_VOSK_MODEL = None


def _get_model():
    global _VOSK_MODEL
    if _VOSK_MODEL is None:
        print(f"Vosk モデルを読み込みます: {VOSK_MODEL_PATH}")
        _VOSK_MODEL = Model(VOSK_MODEL_PATH)
    return _VOSK_MODEL


def _normalize(text):
    return text.replace(" ", "").replace("　", "")


def detect_commands(filename) -> list[str]:
    """WAVファイルからVOSKで固定コマンドを検出し、コマンド名リストを返す。"""
    model = _get_model()

    with wave.open(filename, "rb") as wav:
        rec = KaldiRecognizer(model, wav.getframerate(), VOSK_GRAMMAR)
        parts = []
        while True:
            data = wav.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                t = json.loads(rec.Result()).get("text", "")
                if t:
                    parts.append(t)
        t = json.loads(rec.FinalResult()).get("text", "")
        if t:
            parts.append(t)

    recognized = _normalize(" ".join(parts))
    print(f"Vosk 認識: {recognized or '(なし)'}")

    detected = [
        cmd for cmd, grammar in COMMANDS.items()
        if _normalize(cmd) in recognized or _normalize(grammar) in recognized
    ]

    if detected:
        print(f"Vosk コマンド検出: {', '.join(detected)}")
    else:
        print("Vosk コマンド: 未検出")

    return detected

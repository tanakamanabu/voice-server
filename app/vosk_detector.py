"""
VOSK による固定コマンド検出。

grammar はDBから動的にロードし、管理画面の「反映」ボタンで reload_grammar() を
呼び出すことで再起動なしに更新できる。
"""

import json
import logging
import os
import wave

from vosk import KaldiRecognizer, Model

import database

logger = logging.getLogger(__name__)

VOSK_MODEL_PATH = os.getenv("VOSK_MODEL_PATH", "vosk-model-ja-0.22")

_vosk_model = None
_grammar_map: dict[str, str] = {}   # grammar トークン → コマンド名
_vosk_grammar: str = json.dumps(["[unk]"], ensure_ascii=False)


def _get_model() -> Model:
    global _vosk_model
    if _vosk_model is None:
        logger.info("Vosk モデルを読み込みます: %s", VOSK_MODEL_PATH)
        _vosk_model = Model(VOSK_MODEL_PATH)
    return _vosk_model


def reload_grammar():
    """DBから grammar をリロードする。起動時と管理画面の「反映」ボタン押下時に呼ぶ。"""
    global _grammar_map, _vosk_grammar
    _grammar_map = database.get_grammar_map()
    _vosk_grammar = json.dumps(
        list(_grammar_map.keys()) + ["[unk]"],
        ensure_ascii=False,
    )
    logger.info("VOSKのgrammarをリロードしました（%d件）", len(_grammar_map))


def detect_commands(filename: str) -> list[str]:
    """
    WAVファイルからVOSKで固定コマンドを検出し、コマンド名リストを返す。
    grammarに登録されたトークンに完全一致したものを返す。
    """
    model = _get_model()

    with wave.open(filename, "rb") as wav:
        rec = KaldiRecognizer(model, wav.getframerate(), _vosk_grammar)
        parts: list[str] = []
        while True:
            data = wav.readframes(4000)
            if not data:
                break
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
                if text and text != "[unk]":
                    parts.append(text)
        final = json.loads(rec.FinalResult()).get("text", "")
        if final and final != "[unk]":
            parts.append(final)

    logger.info("Vosk 認識: %s", ", ".join(parts) if parts else "(なし)")

    # 認識されたgrammarトークンをコマンド名に変換（重複除去・順序保持）
    seen: set[str] = set()
    detected: list[str] = []
    for token in parts:
        cmd_name = _grammar_map.get(token)
        if cmd_name and cmd_name not in seen:
            detected.append(cmd_name)
            seen.add(cmd_name)

    if detected:
        logger.info("Vosk コマンド検出: %s", ", ".join(detected))
    else:
        logger.info("Vosk コマンド: 未検出")

    return detected

"""
VoiceVox エンジンを使った WAV 事前合成。

管理画面で応答テキストを保存・再生成する際に呼び出す。
実行時（/voice リクエスト）は生成済み WAV ファイルを直接返すだけなので
このモジュールは呼び出さない。
"""

import logging
import os
from pathlib import Path

import requests

import database

logger = logging.getLogger(__name__)

VOICEVOX_URL  = os.getenv("VOICEVOX_URL",  "http://voicevox:50021")
RESPONSES_DIR = Path(os.getenv("RESPONSES_DIR", "/app/data/responses"))


def _synthesize(text: str, speaker_id: int) -> bytes:
    """テキストを VoiceVox で合成し WAV バイト列を返す。"""
    resp = requests.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker_id},
        timeout=30,
    )
    resp.raise_for_status()
    audio_query = resp.json()

    resp = requests.post(
        f"{VOICEVOX_URL}/synthesis",
        params={"speaker": speaker_id},
        json=audio_query,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def _save_wav(wav_bytes: bytes, filename: str) -> str:
    """WAV バイト列をファイルに保存し、パスを返す。"""
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    path = RESPONSES_DIR / filename
    path.write_bytes(wav_bytes)
    logger.info("WAV 保存: %s (%d bytes)", path, len(wav_bytes))
    return str(path)


def _get_speaker_id(character_id: int) -> int:
    """キャラクター ID から VoiceVox スピーカー ID を取得する。"""
    char = database.get_character(character_id)
    if char is None:
        raise ValueError(f"キャラクターが見つかりません: id={character_id}")
    return char["voicevox_speaker_id"]


def generate_response_wav(response_id: int, character_id: int) -> str:
    """
    command_responses の WAV を指定キャラクターで生成・保存する。
    DB の command_response_wavs も更新する。
    """
    row = database.get_response(response_id)
    if row is None:
        raise ValueError(f"command_responses に id={response_id} が見つかりません")

    speaker_id = _get_speaker_id(character_id)
    logger.info(
        "WAV 生成: response_id=%d character_id=%d speaker=%d text=%s",
        response_id, character_id, speaker_id, row["text"],
    )

    wav_bytes = _synthesize(row["text"], speaker_id)
    wav_path  = _save_wav(wav_bytes, f"response_{response_id}_char_{character_id}.wav")

    database.upsert_response_wav(response_id, character_id, wav_path)
    return wav_path


def generate_fallback_wav(fallback_id: int, character_id: int) -> str:
    """
    fallback_responses の WAV を指定キャラクターで生成・保存する。
    DB の fallback_response_wavs も更新する。
    """
    row = database.get_fallback(fallback_id)
    if row is None:
        raise ValueError(f"fallback_responses に id={fallback_id} が見つかりません")

    speaker_id = _get_speaker_id(character_id)
    logger.info(
        "WAV 生成: fallback_id=%d character_id=%d speaker=%d text=%s",
        fallback_id, character_id, speaker_id, row["text"],
    )

    wav_bytes = _synthesize(row["text"], speaker_id)
    wav_path  = _save_wav(wav_bytes, f"fallback_{fallback_id}_char_{character_id}.wav")

    database.upsert_fallback_wav(fallback_id, character_id, wav_path)
    return wav_path


def generate_all_response_wavs(response_id: int) -> list[tuple[int, str | None]]:
    """
    全キャラクター分の WAV を一括生成する。
    戻り値: [(character_id, wav_path_or_None), ...]
    """
    characters = database.get_all_characters()
    results = []
    for char in characters:
        try:
            path = generate_response_wav(response_id, char["id"])
            results.append((char["id"], path))
        except Exception as exc:
            logger.error(
                "WAV 生成失敗: response_id=%d character_id=%d — %s",
                response_id, char["id"], exc,
            )
            results.append((char["id"], None))
    return results


def generate_all_fallback_wavs(fallback_id: int) -> list[tuple[int, str | None]]:
    """
    全キャラクター分のフォールバック WAV を一括生成する。
    戻り値: [(character_id, wav_path_or_None), ...]
    """
    characters = database.get_all_characters()
    results = []
    for char in characters:
        try:
            path = generate_fallback_wav(fallback_id, char["id"])
            results.append((char["id"], path))
        except Exception as exc:
            logger.error(
                "WAV 生成失敗: fallback_id=%d character_id=%d — %s",
                fallback_id, char["id"], exc,
            )
            results.append((char["id"], None))
    return results


def get_speakers() -> list[dict]:
    """
    VoiceVox から話者一覧を取得して返す。
    管理画面のスピーカー選択プルダウン用。
    戻り値例: [{"id": 1, "name": "四国めたん（ノーマル）"}, ...]
    """
    try:
        resp = requests.get(f"{VOICEVOX_URL}/speakers", timeout=10)
        resp.raise_for_status()
        speakers = []
        for speaker in resp.json():
            for style in speaker["styles"]:
                speakers.append({
                    "id":   style["id"],
                    "name": f"{speaker['name']}（{style['name']}）",
                })
        return speakers
    except Exception as exc:
        logger.error("VoiceVox 話者一覧の取得に失敗しました: %s", exc)
        return []

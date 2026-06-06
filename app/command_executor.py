"""
コマンド名をもとにDBを参照し、Home Assistant のサービスを呼び出す。
応答WAVファイルのパスを返す。
"""

import json
import logging
import os

import requests

import database

logger = logging.getLogger(__name__)

HA_URL   = os.getenv("HA_URL",   "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")


def _call_ha(domain: str, service: str, entity_id: str, extra: dict):
    if not HA_TOKEN:
        logger.warning("HA_TOKEN 未設定 — Home Assistant 呼び出しをスキップします")
        return
    url     = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    data    = {"entity_id": entity_id, **extra}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=5)
        resp.raise_for_status()
        logger.info("HA %s.%s → %s", domain, service, resp.status_code)
    except Exception as exc:
        logger.error("HA 呼び出し失敗: %s", exc)


def execute(command_name: str, character_id: int) -> str | None:
    """
    コマンドを実行し、応答WAVファイルのパスを返す。
    WAVが未生成またはコマンドが存在しない場合は None を返す。
    """
    cmd = database.get_command_by_name(command_name)
    if cmd is None:
        logger.warning("DBにコマンドが見つかりません: %s", command_name)
        return None

    # Home Assistant 呼び出し
    if cmd["ha_domain"] and cmd["ha_service"] and cmd["ha_entity_id"]:
        extra = json.loads(cmd["ha_extra"] or "{}")
        _call_ha(cmd["ha_domain"], cmd["ha_service"], cmd["ha_entity_id"], extra)

    # アクティブキャラクターの WAV をランダム選択
    wav_path = database.get_random_response(cmd["id"], character_id)
    if wav_path is None:
        logger.warning(
            "応答WAVが未生成です（コマンド: %s, character_id: %d）。管理画面でWAVを生成してください。",
            command_name, character_id,
        )
    return wav_path

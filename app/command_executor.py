import logging
import os
import requests

logger = logging.getLogger(__name__)

HA_URL = os.getenv("HA_URL", "http://localhost:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")


def _ha(domain, service, data):
    if not HA_TOKEN:
        logger.warning("HA_TOKEN 未設定 — Home Assistant 呼び出しをスキップします")
        return
    url = f"{HA_URL}/api/services/{domain}/{service}"
    headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=5)
        resp.raise_for_status()
        logger.info("HA %s.%s → %s", domain, service, resp.status_code)
    except Exception as exc:
        logger.error("HA 呼び出し失敗: %s", exc)


# 各コマンドの (実行関数, 応答テキスト)
_LIGHT  = lambda: os.getenv("HA_LIGHT_ENTITY",  "light.living_room")
_AC     = lambda: os.getenv("HA_AC_ENTITY",     "climate.living_room")
_PC     = lambda: os.getenv("HA_PC_ENTITY",     "switch.pc")

COMMANDS: dict[str, tuple] = {
    "ライトオン":    (lambda: _ha("light",   "turn_on",       {"entity_id": _LIGHT()}),                                  "ライトをオンにします"),
    "ライトオフ":    (lambda: _ha("light",   "turn_off",      {"entity_id": _LIGHT()}),                                  "ライトをオフにします"),
    "冷房オン":      (lambda: _ha("climate", "set_hvac_mode", {"entity_id": _AC(), "hvac_mode": "cool"}),                "冷房をオンにします"),
    "暖房オン":      (lambda: _ha("climate", "set_hvac_mode", {"entity_id": _AC(), "hvac_mode": "heat"}),                "暖房をオンにします"),
    "エアコンオフ":  (lambda: _ha("climate", "turn_off",      {"entity_id": _AC()}),                                    "エアコンをオフにします"),
    "学習開始":      (None,                                                                                               "学習を開始します"),
    "パソコンつけて": (lambda: _ha("switch",  "turn_on",       {"entity_id": _PC()}),                                    "パソコンをつけます"),
}


def execute(command: str) -> str:
    """コマンドを実行し、音声応答テキストを返す。"""
    entry = COMMANDS.get(command)
    if entry is None:
        logger.warning("未知のコマンド: %s", command)
        return f"{command}は対応していません"

    action, response = entry
    if action:
        action()
    return response

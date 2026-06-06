"""
SQLite によるコマンド管理 DB。
起動時に init_db() を呼び出すことでテーブル作成と初期データ投入を行う。
"""

import json
import logging
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/commands.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    """コネクションを都度生成するコンテキストマネージャ（スレッドセーフ）。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# スキーマ初期化
# ---------------------------------------------------------------------------

def init_db():
    """テーブル作成と初期データ投入を行う。起動時に呼び出す。"""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT NOT NULL UNIQUE,
                voicevox_speaker_id INTEGER NOT NULL DEFAULT 0,
                synthesis_type      TEXT NOT NULL DEFAULT 'voicevox',
                is_active           INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT NOT NULL
            )
        """)
        # マイグレーション: 既存テーブルに synthesis_type がなければ追加
        existing_cols = [
            row[1] for row in conn.execute("PRAGMA table_info(characters)").fetchall()
        ]
        if "synthesis_type" not in existing_cols:
            conn.execute(
                "ALTER TABLE characters ADD COLUMN synthesis_type TEXT NOT NULL DEFAULT 'voicevox'"
            )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                ha_domain    TEXT,
                ha_service   TEXT,
                ha_entity_id TEXT,
                ha_extra     TEXT NOT NULL DEFAULT '{}',
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_grammars (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                command_id INTEGER NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
                grammar    TEXT NOT NULL,
                UNIQUE(command_id, grammar)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_responses (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                command_id INTEGER NOT NULL REFERENCES commands(id) ON DELETE CASCADE,
                text       TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS command_response_wavs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                response_id  INTEGER NOT NULL REFERENCES command_responses(id) ON DELETE CASCADE,
                character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                wav_path     TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(response_id, character_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fallback_responses (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                text    TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS fallback_response_wavs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fallback_id  INTEGER NOT NULL REFERENCES fallback_responses(id) ON DELETE CASCADE,
                character_id INTEGER NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                wav_path     TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                UNIQUE(fallback_id, character_id)
            )
        """)

    _seed_initial_data()
    logger.info("DB初期化完了: %s", DB_PATH)


def _seed_initial_data():
    """各テーブルが空の場合のみ初期データを投入する。"""
    with get_db() as conn:
        has_chars    = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] > 0
        has_commands = conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] > 0
        if has_chars and has_commands:
            return

    now   = _now()
    light = os.getenv("HA_LIGHT_ENTITY", "light.living_room")
    ac    = os.getenv("HA_AC_ENTITY",    "climate.living_room")
    pc    = os.getenv("HA_PC_ENTITY",    "switch.pc")

    SEED_COMMANDS = [
        {"name": "ライトオン",    "ha_domain": "light",    "ha_service": "turn_on",       "ha_entity_id": light, "ha_extra": "{}",
         "grammars": ["ライト オン"],    "responses": ["ライトをオンにします"]},
        {"name": "ライトオフ",    "ha_domain": "light",    "ha_service": "turn_off",      "ha_entity_id": light, "ha_extra": "{}",
         "grammars": ["ライト オフ"],    "responses": ["ライトをオフにします"]},
        {"name": "冷房オン",      "ha_domain": "climate",  "ha_service": "set_hvac_mode", "ha_entity_id": ac,
         "ha_extra": json.dumps({"hvac_mode": "cool"}, ensure_ascii=False),
         "grammars": ["冷房 オン"],      "responses": ["冷房をオンにします"]},
        {"name": "暖房オン",      "ha_domain": "climate",  "ha_service": "set_hvac_mode", "ha_entity_id": ac,
         "ha_extra": json.dumps({"hvac_mode": "heat"}, ensure_ascii=False),
         "grammars": ["暖房 オン"],      "responses": ["暖房をオンにします"]},
        {"name": "エアコンオフ",  "ha_domain": "climate",  "ha_service": "turn_off",      "ha_entity_id": ac,    "ha_extra": "{}",
         "grammars": ["エアコン オフ"],  "responses": ["エアコンをオフにします"]},
        {"name": "学習開始",      "ha_domain": None,       "ha_service": None,            "ha_entity_id": None,  "ha_extra": "{}",
         "grammars": ["学習 開始"],      "responses": ["学習を開始します"]},
        {"name": "パソコンつけて","ha_domain": "switch",   "ha_service": "turn_on",       "ha_entity_id": pc,    "ha_extra": "{}",
         "grammars": ["パソコン つけて"],"responses": ["パソコンをつけます"]},
    ]

    SEED_FALLBACKS = [
        "すみません、よく聞き取れませんでした",
        "もう一度おっしゃっていただけますか？",
    ]

    with get_db() as conn:
        if not has_chars:
            conn.execute(
                """INSERT INTO characters
                       (name, voicevox_speaker_id, synthesis_type, is_active, created_at)
                   VALUES (?,?,?,1,?)""",
                ("デフォルト", 1, "voicevox", now),
            )

        if not has_commands:
            for cmd in SEED_COMMANDS:
                cur = conn.execute(
                    """INSERT INTO commands
                           (name, ha_domain, ha_service, ha_entity_id, ha_extra, enabled, created_at, updated_at)
                       VALUES (?,?,?,?,?,1,?,?)""",
                    (cmd["name"], cmd["ha_domain"], cmd["ha_service"],
                     cmd["ha_entity_id"], cmd["ha_extra"], now, now),
                )
                cmd_id = cur.lastrowid
                for g in cmd["grammars"]:
                    conn.execute(
                        "INSERT INTO command_grammars (command_id, grammar) VALUES (?,?)",
                        (cmd_id, g),
                    )
                for t in cmd["responses"]:
                    conn.execute(
                        "INSERT INTO command_responses (command_id, text) VALUES (?,?)",
                        (cmd_id, t),
                    )
            for t in SEED_FALLBACKS:
                conn.execute(
                    "INSERT INTO fallback_responses (text, enabled) VALUES (?,1)", (t,)
                )

    logger.info("初期データを投入しました")


# ---------------------------------------------------------------------------
# characters CRUD
# ---------------------------------------------------------------------------

def get_all_characters():
    with get_db() as conn:
        return conn.execute("SELECT * FROM characters ORDER BY id").fetchall()


def get_character(character_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM characters WHERE id=?", (character_id,)
        ).fetchone()


def get_active_character():
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM characters WHERE is_active=1 LIMIT 1"
        ).fetchone()


def create_character(name: str, synthesis_type: str, speaker_id: int = 0) -> int:
    """
    synthesis_type: 'voicevox' | 'upload'
    speaker_id: voicevox タイプのみ使用。upload タイプは 0 でよい。
    """
    with get_db() as conn:
        # 初めてのキャラクターはアクティブにする
        is_first = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0] == 0
        cur = conn.execute(
            """INSERT INTO characters
                   (name, voicevox_speaker_id, synthesis_type, is_active, created_at)
               VALUES (?,?,?,?,?)""",
            (name, speaker_id, synthesis_type, 1 if is_first else 0, _now()),
        )
        return cur.lastrowid


def update_character(character_id: int, name: str, synthesis_type: str, speaker_id: int = 0):
    with get_db() as conn:
        conn.execute(
            "UPDATE characters SET name=?, voicevox_speaker_id=?, synthesis_type=? WHERE id=?",
            (name, speaker_id, synthesis_type, character_id),
        )


def delete_character(character_id: int):
    """ON DELETE CASCADE により関連 WAV レコードも削除される。"""
    with get_db() as conn:
        conn.execute("DELETE FROM characters WHERE id=?", (character_id,))


def set_active_character(character_id: int):
    with get_db() as conn:
        conn.execute("UPDATE characters SET is_active=0")
        conn.execute("UPDATE characters SET is_active=1 WHERE id=?", (character_id,))


# ---------------------------------------------------------------------------
# commands CRUD
# ---------------------------------------------------------------------------

def get_all_commands():
    with get_db() as conn:
        return conn.execute("""
            SELECT
                c.*,
                COUNT(DISTINCT g.id) AS grammar_count,
                COUNT(DISTINCT r.id) AS response_count
            FROM commands c
            LEFT JOIN command_grammars  g ON g.command_id = c.id
            LEFT JOIN command_responses r ON r.command_id = c.id
            GROUP BY c.id
            ORDER BY c.id
        """).fetchall()


def get_command(command_id: int):
    with get_db() as conn:
        return conn.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()


def get_command_by_name(name: str):
    with get_db() as conn:
        return conn.execute("SELECT * FROM commands WHERE name=?", (name,)).fetchone()


def create_command(name, ha_domain, ha_service, ha_entity_id, ha_extra="{}") -> int:
    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO commands
                   (name, ha_domain, ha_service, ha_entity_id, ha_extra, enabled, created_at, updated_at)
               VALUES (?,?,?,?,?,1,?,?)""",
            (name, ha_domain or None, ha_service or None,
             ha_entity_id or None, ha_extra or "{}", now, now),
        )
        return cur.lastrowid


def update_command(command_id: int, name, ha_domain, ha_service, ha_entity_id, ha_extra="{}"):
    with get_db() as conn:
        conn.execute(
            """UPDATE commands
               SET name=?, ha_domain=?, ha_service=?, ha_entity_id=?, ha_extra=?, updated_at=?
               WHERE id=?""",
            (name, ha_domain or None, ha_service or None,
             ha_entity_id or None, ha_extra or "{}", _now(), command_id),
        )


def delete_command(command_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM commands WHERE id=?", (command_id,))


def set_command_enabled(command_id: int, enabled: bool):
    with get_db() as conn:
        conn.execute(
            "UPDATE commands SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, _now(), command_id),
        )


# ---------------------------------------------------------------------------
# command_grammars CRUD
# ---------------------------------------------------------------------------

def get_grammars_for_command(command_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM command_grammars WHERE command_id=? ORDER BY id",
            (command_id,),
        ).fetchall()


def get_grammar_map() -> dict[str, str]:
    """VOSK用: grammar トークン → コマンド名 辞書（有効コマンドのみ）。"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT g.grammar, c.name
            FROM command_grammars g
            JOIN commands c ON c.id = g.command_id
            WHERE c.enabled = 1
        """).fetchall()
    return {row["grammar"]: row["name"] for row in rows}


def add_grammar(command_id: int, grammar: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO command_grammars (command_id, grammar) VALUES (?,?)",
            (command_id, grammar),
        )
        return cur.lastrowid


def delete_grammar(grammar_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM command_grammars WHERE id=?", (grammar_id,))


# ---------------------------------------------------------------------------
# command_responses CRUD
# ---------------------------------------------------------------------------

def get_responses_for_command(command_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM command_responses WHERE command_id=? ORDER BY id",
            (command_id,),
        ).fetchall()


def get_response(response_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM command_responses WHERE id=?", (response_id,)
        ).fetchone()


def add_response(command_id: int, text: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO command_responses (command_id, text) VALUES (?,?)",
            (command_id, text),
        )
        return cur.lastrowid


def delete_response(response_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM command_responses WHERE id=?", (response_id,))


def get_random_response(command_id: int, character_id: int):
    """指定キャラクターの WAV 生成済み応答からランダムに1件返す。"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT w.wav_path
            FROM command_response_wavs w
            JOIN command_responses r ON r.id = w.response_id
            WHERE r.command_id=? AND w.character_id=?
        """, (command_id, character_id)).fetchall()
    return random.choice(rows)["wav_path"] if rows else None


# ---------------------------------------------------------------------------
# command_response_wavs
# ---------------------------------------------------------------------------

def get_response_wavs(response_id: int) -> dict[int, sqlite3.Row]:
    """character_id → wav_row のマップを返す。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM command_response_wavs WHERE response_id=?", (response_id,)
        ).fetchall()
    return {row["character_id"]: row for row in rows}


def upsert_response_wav(response_id: int, character_id: int, wav_path: str):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO command_response_wavs (response_id, character_id, wav_path, generated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(response_id, character_id) DO UPDATE SET wav_path=excluded.wav_path, generated_at=excluded.generated_at
        """, (response_id, character_id, wav_path, _now()))


def delete_response_wav(response_id: int, character_id: int):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM command_response_wavs WHERE response_id=? AND character_id=?",
            (response_id, character_id),
        )


# ---------------------------------------------------------------------------
# fallback_responses CRUD
# ---------------------------------------------------------------------------

def get_all_fallbacks():
    with get_db() as conn:
        return conn.execute("SELECT * FROM fallback_responses ORDER BY id").fetchall()


def get_fallback(fallback_id: int):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM fallback_responses WHERE id=?", (fallback_id,)
        ).fetchone()


def add_fallback(text: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO fallback_responses (text, enabled) VALUES (?,1)", (text,)
        )
        return cur.lastrowid


def delete_fallback(fallback_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM fallback_responses WHERE id=?", (fallback_id,))


def set_fallback_enabled(fallback_id: int, enabled: bool):
    with get_db() as conn:
        conn.execute(
            "UPDATE fallback_responses SET enabled=? WHERE id=?",
            (1 if enabled else 0, fallback_id),
        )


def get_random_fallback(character_id: int):
    """有効かつ指定キャラクターの WAV 生成済みフォールバックからランダムに1件返す。"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT w.wav_path
            FROM fallback_response_wavs w
            JOIN fallback_responses f ON f.id = w.fallback_id
            WHERE f.enabled=1 AND w.character_id=?
        """, (character_id,)).fetchall()
    return random.choice(rows)["wav_path"] if rows else None


# ---------------------------------------------------------------------------
# fallback_response_wavs
# ---------------------------------------------------------------------------

def get_fallback_wavs(fallback_id: int) -> dict[int, sqlite3.Row]:
    """character_id → wav_row のマップを返す。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM fallback_response_wavs WHERE fallback_id=?", (fallback_id,)
        ).fetchall()
    return {row["character_id"]: row for row in rows}


def upsert_fallback_wav(fallback_id: int, character_id: int, wav_path: str):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO fallback_response_wavs (fallback_id, character_id, wav_path, generated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(fallback_id, character_id) DO UPDATE SET wav_path=excluded.wav_path, generated_at=excluded.generated_at
        """, (fallback_id, character_id, wav_path, _now()))


def delete_fallback_wav(fallback_id: int, character_id: int):
    with get_db() as conn:
        conn.execute(
            "DELETE FROM fallback_response_wavs WHERE fallback_id=? AND character_id=?",
            (fallback_id, character_id),
        )

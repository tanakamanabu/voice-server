"""管理画面 Blueprint。"""

import logging
import os
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

import database
import voicevox
import vosk_detector

RESPONSES_DIR = Path(os.getenv("RESPONSES_DIR", "/app/data/responses"))

logger = logging.getLogger(__name__)

admin = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _delete_wav(wav_path: str | None):
    """WAV ファイルが存在すれば削除する。"""
    if wav_path and os.path.exists(wav_path):
        try:
            os.unlink(wav_path)
        except OSError as exc:
            logger.warning("WAV削除失敗: %s — %s", wav_path, exc)


def _save_uploaded_wav(filename_stem: str, file) -> str:
    """
    アップロードされた WAV ファイルを保存してパスを返す。
    filename_stem 例: 'response_3_char_2'
    """
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    path = RESPONSES_DIR / f"{filename_stem}.wav"
    file.save(str(path))
    logger.info("WAV アップロード保存: %s", path)
    return str(path)


def _delete_response_all_wavs(response_id: int):
    """response の全キャラクター WAV ファイルを削除する。"""
    wavs = database.get_response_wavs(response_id)
    for wav_row in wavs.values():
        _delete_wav(wav_row["wav_path"])


def _delete_fallback_all_wavs(fallback_id: int):
    """fallback の全キャラクター WAV ファイルを削除する。"""
    wavs = database.get_fallback_wavs(fallback_id)
    for wav_row in wavs.values():
        _delete_wav(wav_row["wav_path"])


# ---------------------------------------------------------------------------
# コマンド一覧
# ---------------------------------------------------------------------------

@admin.route("/")
def index():
    commands = database.get_all_commands()
    return render_template("admin/index.html", commands=commands)


# ---------------------------------------------------------------------------
# コマンド 新規作成 / 編集
# ---------------------------------------------------------------------------

@admin.route("/commands/new", methods=["GET", "POST"])
def command_new():
    if request.method == "POST":
        name         = request.form["name"].strip()
        ha_domain    = request.form.get("ha_domain", "").strip()
        ha_service   = request.form.get("ha_service", "").strip()
        ha_entity_id = request.form.get("ha_entity_id", "").strip()
        ha_extra     = request.form.get("ha_extra", "{}").strip() or "{}"
        try:
            cmd_id = database.create_command(name, ha_domain, ha_service, ha_entity_id, ha_extra)
            flash(f"コマンド「{name}」を作成しました", "success")
            return redirect(url_for("admin.command_edit", command_id=cmd_id))
        except Exception as exc:
            flash(f"作成に失敗しました: {exc}", "danger")
    return render_template("admin/command_form.html",
                           command=None, characters=[], grammars=[],
                           responses=[], response_wavs={})


@admin.route("/commands/<int:command_id>/edit", methods=["GET", "POST"])
def command_edit(command_id):
    cmd = database.get_command(command_id)
    if cmd is None:
        flash("コマンドが見つかりません", "danger")
        return redirect(url_for("admin.index"))

    if request.method == "POST":
        name         = request.form["name"].strip()
        ha_domain    = request.form.get("ha_domain", "").strip()
        ha_service   = request.form.get("ha_service", "").strip()
        ha_entity_id = request.form.get("ha_entity_id", "").strip()
        ha_extra     = request.form.get("ha_extra", "{}").strip() or "{}"
        enabled      = bool(request.form.get("enabled"))
        try:
            database.update_command(command_id, name, ha_domain, ha_service, ha_entity_id, ha_extra)
            database.set_command_enabled(command_id, enabled)
            flash("保存しました", "success")
        except Exception as exc:
            flash(f"保存に失敗しました: {exc}", "danger")
        return redirect(url_for("admin.command_edit", command_id=command_id))

    grammars   = database.get_grammars_for_command(command_id)
    responses  = database.get_responses_for_command(command_id)
    characters = database.get_all_characters()
    response_wavs = {r["id"]: database.get_response_wavs(r["id"]) for r in responses}

    return render_template("admin/command_form.html",
                           command=cmd, characters=characters,
                           grammars=grammars, responses=responses,
                           response_wavs=response_wavs)


@admin.route("/commands/<int:command_id>/delete", methods=["POST"])
def command_delete(command_id):
    for r in database.get_responses_for_command(command_id):
        _delete_response_all_wavs(r["id"])
    database.delete_command(command_id)
    flash("コマンドを削除しました", "success")
    return redirect(url_for("admin.index"))


# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------

@admin.route("/commands/<int:command_id>/grammars", methods=["POST"])
def grammar_add(command_id):
    grammar = request.form["grammar"].strip()
    if grammar:
        database.add_grammar(command_id, grammar)
        flash(f"grammar を追加しました: {grammar}", "success")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/grammars/<int:grammar_id>/delete", methods=["POST"])
def grammar_delete(grammar_id):
    command_id = request.form.get("command_id", type=int)
    database.delete_grammar(grammar_id)
    flash("grammar を削除しました", "success")
    return redirect(url_for("admin.command_edit", command_id=command_id))


# ---------------------------------------------------------------------------
# 応答テキスト / WAV
# ---------------------------------------------------------------------------

@admin.route("/commands/<int:command_id>/responses", methods=["POST"])
def response_add(command_id):
    text = request.form["text"].strip()
    if not text:
        flash("テキストを入力してください", "warning")
        return redirect(url_for("admin.command_edit", command_id=command_id))

    response_id = database.add_response(command_id, text)

    # voicevox タイプのキャラクター分を一括生成（upload タイプはスキップ）
    results    = voicevox.generate_all_response_wavs(response_id)
    ok         = sum(1 for _, p in results if p)
    ng         = sum(1 for _, p in results if not p)
    upload_cnt = sum(1 for c in database.get_all_characters() if c["synthesis_type"] == "upload")

    msg = f"応答テキストを追加しました"
    if results:
        msg += f"（VoiceVox: {ok} 件生成"
        if ng:
            msg += f"、{ng} 件失敗"
        msg += "）"
    if upload_cnt:
        msg += f"。アップロード型キャラクター {upload_cnt} 件は手動で WAV を登録してください。"
    flash(msg, "success" if ng == 0 else "warning")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/regenerate", methods=["POST"])
def response_regenerate(response_id):
    command_id   = request.form.get("command_id", type=int)
    character_id = request.form.get("character_id", type=int)
    try:
        voicevox.generate_response_wav(response_id, character_id)
        flash("WAV を再生成しました", "success")
    except Exception as exc:
        flash(f"WAV 再生成に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/regenerate_all", methods=["POST"])
def response_regenerate_all(response_id):
    command_id = request.form.get("command_id", type=int)
    results = voicevox.generate_all_response_wavs(response_id)
    ok = sum(1 for _, p in results if p)
    ng = sum(1 for _, p in results if not p)
    if ng == 0:
        flash(f"全 {ok} キャラクター分の WAV を再生成しました", "success")
    else:
        flash(f"WAV 再生成: {ok} 件成功、{ng} 件失敗", "warning")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/delete", methods=["POST"])
def response_delete(response_id):
    command_id = request.form.get("command_id", type=int)
    _delete_response_all_wavs(response_id)
    database.delete_response(response_id)
    flash("応答を削除しました", "success")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/upload", methods=["POST"])
def response_upload_wav(response_id):
    """アップロードされた WAV ファイルを応答に登録する。"""
    command_id   = request.form.get("command_id", type=int)
    character_id = request.form.get("character_id", type=int)
    file = request.files.get("wav_file")

    if not file or file.filename == "":
        flash("WAV ファイルを選択してください", "warning")
        return redirect(url_for("admin.command_edit", command_id=command_id))
    if not file.filename.lower().endswith(".wav"):
        flash("WAV ファイル（.wav）のみアップロードできます", "warning")
        return redirect(url_for("admin.command_edit", command_id=command_id))

    try:
        wav_path = _save_uploaded_wav(f"response_{response_id}_char_{character_id}", file)
        database.upsert_response_wav(response_id, character_id, wav_path)
        flash("WAV をアップロードしました", "success")
    except Exception as exc:
        flash(f"アップロードに失敗しました: {exc}", "danger")
    return redirect(url_for("admin.command_edit", command_id=command_id))


# ---------------------------------------------------------------------------
# フォールバック応答
# ---------------------------------------------------------------------------

@admin.route("/fallback", methods=["GET", "POST"])
def fallback_index():
    if request.method == "POST":
        text = request.form["text"].strip()
        if not text:
            flash("テキストを入力してください", "warning")
            return redirect(url_for("admin.fallback_index"))
        fallback_id = database.add_fallback(text)
        results = voicevox.generate_all_fallback_wavs(fallback_id)
        ok = sum(1 for _, p in results if p)
        ng = sum(1 for _, p in results if not p)
        if ng == 0:
            flash(f"フォールバック応答を追加し、全 {ok} キャラクター分の WAV を生成しました", "success")
        else:
            flash(
                f"フォールバック応答を追加しました（WAV: {ok} 件成功、{ng} 件失敗）",
                "warning",
            )
        return redirect(url_for("admin.fallback_index"))

    fallbacks     = database.get_all_fallbacks()
    characters    = database.get_all_characters()
    fallback_wavs = {f["id"]: database.get_fallback_wavs(f["id"]) for f in fallbacks}
    return render_template("admin/fallback.html",
                           fallbacks=fallbacks,
                           characters=characters,
                           fallback_wavs=fallback_wavs)


@admin.route("/fallback/<int:fallback_id>/regenerate", methods=["POST"])
def fallback_regenerate(fallback_id):
    character_id = request.form.get("character_id", type=int)
    try:
        voicevox.generate_fallback_wav(fallback_id, character_id)
        flash("WAV を再生成しました", "success")
    except Exception as exc:
        flash(f"WAV 再生成に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.fallback_index"))


@admin.route("/fallback/<int:fallback_id>/regenerate_all", methods=["POST"])
def fallback_regenerate_all(fallback_id):
    results = voicevox.generate_all_fallback_wavs(fallback_id)
    ok = sum(1 for _, p in results if p)
    ng = sum(1 for _, p in results if not p)
    if ng == 0:
        flash(f"全 {ok} キャラクター分の WAV を再生成しました", "success")
    else:
        flash(f"WAV 再生成: {ok} 件成功、{ng} 件失敗", "warning")
    return redirect(url_for("admin.fallback_index"))


@admin.route("/fallback/<int:fallback_id>/delete", methods=["POST"])
def fallback_delete(fallback_id):
    _delete_fallback_all_wavs(fallback_id)
    database.delete_fallback(fallback_id)
    flash("フォールバック応答を削除しました", "success")
    return redirect(url_for("admin.fallback_index"))


@admin.route("/fallback/<int:fallback_id>/upload", methods=["POST"])
def fallback_upload_wav(fallback_id):
    """アップロードされた WAV ファイルをフォールバックに登録する。"""
    character_id = request.form.get("character_id", type=int)
    file = request.files.get("wav_file")

    if not file or file.filename == "":
        flash("WAV ファイルを選択してください", "warning")
        return redirect(url_for("admin.fallback_index"))
    if not file.filename.lower().endswith(".wav"):
        flash("WAV ファイル（.wav）のみアップロードできます", "warning")
        return redirect(url_for("admin.fallback_index"))

    try:
        wav_path = _save_uploaded_wav(f"fallback_{fallback_id}_char_{character_id}", file)
        database.upsert_fallback_wav(fallback_id, character_id, wav_path)
        flash("WAV をアップロードしました", "success")
    except Exception as exc:
        flash(f"アップロードに失敗しました: {exc}", "danger")
    return redirect(url_for("admin.fallback_index"))


# ---------------------------------------------------------------------------
# キャラクター管理
# ---------------------------------------------------------------------------

@admin.route("/characters")
def characters_index():
    characters = database.get_all_characters()
    speakers   = voicevox.get_speakers()
    return render_template("admin/characters.html",
                           characters=characters, speakers=speakers)


@admin.route("/characters/new", methods=["POST"])
def character_new():
    name           = request.form["name"].strip()
    synthesis_type = request.form.get("synthesis_type", "voicevox")
    speaker_id     = request.form.get("speaker_id", type=int) or 0

    if not name:
        flash("名前は必須です", "warning")
        return redirect(url_for("admin.characters_index"))
    if synthesis_type == "voicevox" and not speaker_id:
        flash("VoiceVox タイプはスピーカーを選択してください", "warning")
        return redirect(url_for("admin.characters_index"))
    try:
        database.create_character(name, synthesis_type, speaker_id)
        flash(f"キャラクター「{name}」を作成しました", "success")
    except Exception as exc:
        flash(f"作成に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.characters_index"))


@admin.route("/characters/<int:character_id>/edit", methods=["POST"])
def character_edit(character_id):
    name           = request.form["name"].strip()
    synthesis_type = request.form.get("synthesis_type", "voicevox")
    speaker_id     = request.form.get("speaker_id", type=int) or 0
    try:
        database.update_character(character_id, name, synthesis_type, speaker_id)
        flash("キャラクターを更新しました", "success")
    except Exception as exc:
        flash(f"更新に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.characters_index"))


@admin.route("/characters/<int:character_id>/activate", methods=["POST"])
def character_activate(character_id):
    database.set_active_character(character_id)
    char = database.get_character(character_id)
    flash(f"「{char['name']}」をアクティブキャラクターに設定しました", "success")
    return redirect(url_for("admin.characters_index"))


@admin.route("/characters/<int:character_id>/delete", methods=["POST"])
def character_delete(character_id):
    char = database.get_character(character_id)
    if char is None:
        flash("キャラクターが見つかりません", "danger")
        return redirect(url_for("admin.characters_index"))
    if char["is_active"]:
        flash("アクティブキャラクターは削除できません。先に別のキャラクターをアクティブに設定してください。", "warning")
        return redirect(url_for("admin.characters_index"))
    # WAV ファイルは DB の CASCADE で紐付きレコードが削除されるが、ファイル自体は手動削除
    # （削除対象が広範なためここでは省略 — data/ 以下のファイルは定期クリーンアップ推奨）
    database.delete_character(character_id)
    flash(f"キャラクター「{char['name']}」を削除しました", "success")
    return redirect(url_for("admin.characters_index"))


# ---------------------------------------------------------------------------
# VOSK grammar リロード
# ---------------------------------------------------------------------------

@admin.route("/reload", methods=["POST"])
def reload():
    vosk_detector.reload_grammar()
    flash("VOSK の grammar をリロードしました", "success")
    return redirect(request.referrer or url_for("admin.index"))

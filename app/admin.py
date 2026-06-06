"""管理画面 Blueprint。"""

import logging
import os

from flask import Blueprint, flash, redirect, render_template, request, url_for

import database
import voicevox
import vosk_detector

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
    speakers = voicevox.get_speakers()
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
                           command=None, speakers=speakers, grammars=[], responses=[])


@admin.route("/commands/<int:command_id>/edit", methods=["GET", "POST"])
def command_edit(command_id):
    cmd = database.get_command(command_id)
    if cmd is None:
        flash("コマンドが見つかりません", "danger")
        return redirect(url_for("admin.index"))

    grammars  = database.get_grammars_for_command(command_id)
    responses = database.get_responses_for_command(command_id)
    speakers  = voicevox.get_speakers()

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

    return render_template("admin/command_form.html",
                           command=cmd, speakers=speakers,
                           grammars=grammars, responses=responses)


@admin.route("/commands/<int:command_id>/delete", methods=["POST"])
def command_delete(command_id):
    for r in database.get_responses_for_command(command_id):
        _delete_wav(r["wav_path"])
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
    text       = request.form["text"].strip()
    speaker_id = request.form.get("speaker_id", type=int)
    if not text:
        flash("テキストを入力してください", "warning")
        return redirect(url_for("admin.command_edit", command_id=command_id))

    response_id = database.add_response(command_id, text)
    try:
        voicevox.generate_response_wav(response_id, speaker_id)
        flash("応答テキストを追加し WAV を生成しました", "success")
    except Exception as exc:
        flash(f"WAV 生成に失敗しました（テキストは保存済み）: {exc}", "warning")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/regenerate", methods=["POST"])
def response_regenerate(response_id):
    command_id = request.form.get("command_id", type=int)
    speaker_id = request.form.get("speaker_id", type=int)
    try:
        voicevox.generate_response_wav(response_id, speaker_id)
        flash("WAV を再生成しました", "success")
    except Exception as exc:
        flash(f"WAV 再生成に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.command_edit", command_id=command_id))


@admin.route("/responses/<int:response_id>/delete", methods=["POST"])
def response_delete(response_id):
    command_id = request.form.get("command_id", type=int)
    row = database.get_response(response_id)
    if row:
        _delete_wav(row["wav_path"])
    database.delete_response(response_id)
    flash("応答を削除しました", "success")
    return redirect(url_for("admin.command_edit", command_id=command_id))


# ---------------------------------------------------------------------------
# フォールバック応答
# ---------------------------------------------------------------------------

@admin.route("/fallback", methods=["GET", "POST"])
def fallback_index():
    if request.method == "POST":
        text       = request.form["text"].strip()
        speaker_id = request.form.get("speaker_id", type=int)
        if not text:
            flash("テキストを入力してください", "warning")
            return redirect(url_for("admin.fallback_index"))
        fallback_id = database.add_fallback(text)
        try:
            voicevox.generate_fallback_wav(fallback_id, speaker_id)
            flash("フォールバック応答を追加し WAV を生成しました", "success")
        except Exception as exc:
            flash(f"WAV 生成に失敗しました（テキストは保存済み）: {exc}", "warning")
        return redirect(url_for("admin.fallback_index"))

    fallbacks = database.get_all_fallbacks()
    speakers  = voicevox.get_speakers()
    return render_template("admin/fallback.html", fallbacks=fallbacks, speakers=speakers)


@admin.route("/fallback/<int:fallback_id>/regenerate", methods=["POST"])
def fallback_regenerate(fallback_id):
    speaker_id = request.form.get("speaker_id", type=int)
    try:
        voicevox.generate_fallback_wav(fallback_id, speaker_id)
        flash("WAV を再生成しました", "success")
    except Exception as exc:
        flash(f"WAV 再生成に失敗しました: {exc}", "danger")
    return redirect(url_for("admin.fallback_index"))


@admin.route("/fallback/<int:fallback_id>/delete", methods=["POST"])
def fallback_delete(fallback_id):
    row = database.get_fallback(fallback_id)
    if row:
        _delete_wav(row["wav_path"])
    database.delete_fallback(fallback_id)
    flash("フォールバック応答を削除しました", "success")
    return redirect(url_for("admin.fallback_index"))


# ---------------------------------------------------------------------------
# VOSK grammar リロード
# ---------------------------------------------------------------------------

@admin.route("/reload", methods=["POST"])
def reload():
    vosk_detector.reload_grammar()
    flash("VOSK の grammar をリロードしました", "success")
    return redirect(request.referrer or url_for("admin.index"))

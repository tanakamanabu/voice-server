# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 操作コマンド

```bash
# ビルドして起動（コード変更後）
docker compose up -d --build voice

# 環境変数だけ変えた場合（ビルド不要）
docker compose up -d voice

# ログ確認
docker compose logs -f voice

# 停止・再起動
docker compose down
docker compose restart voice
```

## アーキテクチャ

### リクエスト処理フロー

`POST /voice` に 16kHz モノラル WAV を受け取り、WAV を返す。

```
受信 WAV
  └─ vosk_detector.detect_commands()   # VOSK（固定コマンドのみ認識）
       ├─ コマンドあり → command_executor.execute()  # HA REST API 呼び出し
       └─ コマンドなし → WhisperModel.transcribe()  # 汎用文字起こし
                              ↓
                         espeak-ng で TTS → WAV を返す
```

### モジュール間の責務分担

| ファイル | 役割 |
|---|---|
| `app/main.py` | Flask エントリポイント。フロー制御と TTS のみ担当 |
| `app/vosk_detector.py` | VOSK モデルのシングルトン管理と文法ベースのコマンド検出 |
| `app/command_executor.py` | コマンド名 → HA サービス呼び出しのマッピング。応答テキストを返す |

### VOSK のコマンド定義

`vosk_detector.py` の `COMMANDS` 辞書がコマンド検出の唯一の定義元。

- **キー**: コマンド識別名（`command_executor.py` の `COMMANDS` キーと一致させる必要がある）
- **値**: VOSK 文法トークン（スペース区切りの読み仮名）

新しいコマンドを追加する場合は **両ファイルの `COMMANDS` を必ずセットで更新する**。

### Home Assistant 連携の注意点

`homeassistant` コンテナは `network_mode: host` のため Docker ネットワーク内からサービス名では解決できない。`docker-compose.yml` の `HA_URL` にはホストの実 IP アドレスを指定する（`http://homeassistant:8123` は不可）。

`HA_TOKEN` 未設定時は HA 呼び出しをスキップしてサーバーは正常起動する。

### モデルの配置

| モデル | 場所 | タイミング |
|---|---|---|
| VOSK `vosk-model-ja-0.22` | イメージ内 `/app/vosk-model-ja-0.22/` | Dockerfile ビルド時にダウンロード |
| Whisper `small` | ホスト `./data/` にマウント | 初回リクエスト時に自動ダウンロード |

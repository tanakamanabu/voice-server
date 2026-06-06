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

`POST /voice` に 16kHz モノラル WAV を受け取り、事前合成済みの WAV を返す。

```
受信 WAV
  └─ vosk_detector.detect_commands()   # VOSK（DBからgrammarロード）
       ├─ コマンドあり → command_executor.execute()
       │                  HA REST API 呼び出し + DB からランダム応答WAV取得
       └─ コマンドなし → Whisper（ログ用文字起こし）
                              ↓
                         database.get_random_fallback()
                              ↓
                    事前合成済み WAV をそのまま返す
```

### モジュール間の責務分担

| ファイル | 役割 |
|---|---|
| `app/main.py` | Flask エントリポイント。起動時に `init_db()` と `reload_grammar()` を呼ぶ |
| `app/vosk_detector.py` | VOSK モデルのシングルトン管理。grammarはDBから動的ロード。`reload_grammar()` でホットリロード対応 |
| `app/command_executor.py` | コマンド名でDB参照 → HA REST API 呼び出し → 応答WAVパスを返す |
| `app/database.py` | SQLite CRUD。`init_db()` でテーブル作成と初期データ投入 |
| `app/voicevox.py` | VoiceVox API による WAV 事前合成。キャラクター × 応答の単体・一括生成 |
| `app/admin.py` | 管理画面 Blueprint。コマンド/フォールバック/キャラクター管理 |

### コマンドの追加・変更

ソースコードの編集は不要。管理画面（`/admin`）から操作する。  
grammar を変更した後は管理画面の「VOSKに反映」ボタンを押すこと（再起動不要）。

### キャラクター管理

`/admin/characters` でキャラクターを追加・切り替えできる。

- **characters テーブル**: キャラクター名と VoiceVox speaker_id を管理。`is_active=1` のキャラクターがリクエスト時に使用される
- **WAV はキャラクターごとに個別に保存**: `response_{id}_char_{character_id}.wav` / `fallback_{id}_char_{character_id}.wav`
- 応答テキストを追加すると全キャラクター分の WAV を一括生成する
- スピーカーを変更した場合は管理画面の「全再生成」で既存 WAV を更新すること

### Home Assistant 連携の注意点

`homeassistant` コンテナは `network_mode: host` のため Docker ネットワーク内からサービス名では解決できない。`docker-compose.yml` の `HA_URL` にはホストの実 IP アドレスを指定する（`http://homeassistant:8123` は不可）。

`HA_TOKEN` 未設定時は HA 呼び出しをスキップしてサーバーは正常起動する。

### モデルの配置

| モデル | 場所 | タイミング |
|---|---|---|
| VOSK `vosk-model-ja-0.22` | イメージ内 `/app/vosk-model-ja-0.22/` | Dockerfile ビルド時にダウンロード |
| Whisper `small` | ホスト `./data/cache/` にマウント | 初回リクエスト時に自動ダウンロード |

### データの永続化

```
data/
├── cache/       # Whisper モデルキャッシュ（./data/cache:/root/.cache）
└── app/         # SQLite DB + 事前生成 WAV（./data/app:/app/data）
    ├── commands.db
    └── responses/
```

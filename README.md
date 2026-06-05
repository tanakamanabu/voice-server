# voice-server

ラズパイ（speaker-remote）から受け取った音声を処理し、応答音声を返すサーバー。

- **VOSK**（フルモデル）で固定コマンドを検出 → Home Assistant を操作
- コマンド未検出時は **Whisper**（faster-whisper）でフォールバック文字起こし
- **espeak-ng** で日本語 TTS して WAV を返す

## 構成

```
voice-server/
├── app/
│   ├── main.py              # Flask サーバー（/voice エンドポイント）
│   ├── vosk_detector.py     # VOSK による固定コマンド検出
│   ├── command_executor.py  # Home Assistant REST API 呼び出し
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml
├── data/                    # Whisper モデルキャッシュ（自動生成）
└── hass_config/             # Home Assistant 設定（自動生成）
```

## セットアップ

### 1. 環境変数の設定

`docker-compose.yml` を編集して以下を設定する。

```yaml
environment:
  - HA_URL=http://192.168.1.40:8123     # Home Assistant のホスト IP
  - HA_TOKEN=<長期アクセストークン>      # HA の設定 → プロフィール → セキュリティ で発行
  - HA_LIGHT_ENTITY=light.living_room   # HA のエンティティ ID に合わせて変更
  - HA_AC_ENTITY=climate.living_room
  - HA_PC_ENTITY=switch.pc
```

> **Note** `HA_TOKEN` が未設定でも起動は可能。Home Assistant への呼び出しのみスキップされる。

### 2. 初回ビルドと起動

```bash
docker compose up -d --build
```

初回はVOSKモデル（約1GB）のダウンロードとWhisperモデルのダウンロードが走るため時間がかかる。

---

## 日常操作

### 起動

```bash
docker compose up -d
```

### 停止

```bash
docker compose down
```

### 再起動

```bash
docker compose restart voice
```

全サービスをまとめて再起動する場合:

```bash
docker compose restart
```

### ログ確認

```bash
# リアルタイムで流す
docker compose logs -f voice

# 直近100行だけ見る
docker compose logs --tail=100 voice
```

---

## コードを更新したとき

`app/` 以下のコードを変更した場合はイメージの再ビルドが必要。

```bash
# ビルドして再起動（ダウンタイムあり）
docker compose up -d --build voice

# ビルドだけ先に済ませてから切り替える（ダウンタイム最小）
docker compose build voice
docker compose up -d voice
```

`docker-compose.yml` の環境変数だけ変えた場合はビルド不要。

```bash
docker compose up -d voice
```

---

## 固定コマンドの追加・変更

### 認識ワードの追加

`app/vosk_detector.py` の `COMMANDS` 辞書に追記する。

```python
COMMANDS = {
    "ライトオン":    "ライト オン",
    "テレビつけて":  "テレビ つけて",   # ← 追加例
    ...
}
```

- キー: コマンド名（コード内で使う識別子）
- 値: VOSK に渡す文法トークン（単語間をスペースで区切る）

### 実行内容の追加

`app/command_executor.py` の `COMMANDS` 辞書に追記する。

```python
COMMANDS = {
    ...
    "テレビつけて": (
        lambda: _ha("media_player", "turn_on", {"entity_id": os.getenv("HA_TV_ENTITY", "media_player.tv")}),
        "テレビをつけます",
    ),
}
```

追加後はイメージの再ビルドが必要（[コードを更新したとき](#コードを更新したとき) を参照）。

---

## 対応コマンド一覧

| 発話ワード       | 実行内容                        |
|--------------|-------------------------------|
| ライトオン      | `light.turn_on`               |
| ライトオフ      | `light.turn_off`              |
| 冷房オン       | `climate.set_hvac_mode cool`  |
| 暖房オン       | `climate.set_hvac_mode heat`  |
| エアコンオフ    | `climate.turn_off`            |
| 学習開始       | （HA 未連携・応答のみ）            |
| パソコンつけて  | `switch.turn_on`              |

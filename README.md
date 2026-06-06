# voice-server

ラズパイ（speaker-remote）から受け取った音声を処理し、事前合成済みの応答音声を返すサーバー。

## 機能

- **VOSK**（日本語フルモデル）で固定コマンドを認識 → Home Assistant を操作
- コマンド未検出時は **Whisper**（faster-whisper）でログ用に文字起こし
- 応答音声は **VoiceVox** で事前合成した WAV ファイルをそのまま返す（VOCALOID・録音音声も登録可）
- **管理画面**（`/admin`）でコマンド・応答・キャラクターをすべて管理（ソース変更不要）

## 処理フロー

```
受信 WAV（16kHz モノラル）
  └─ VOSK でコマンド検出（grammar は DB から動的ロード）
       ├─ コマンドあり → Home Assistant REST API 呼び出し
       │                  → アクティブキャラクターの応答 WAV をランダム選択して返す
       └─ コマンドなし → Whisper でログ用文字起こし
                          → アクティブキャラクターのフォールバック WAV をランダム選択して返す
```

## ファイル構成

```
voice-server/
├── app/
│   ├── main.py              # Flask サーバー（/voice エンドポイント）
│   ├── vosk_detector.py     # VOSK による固定コマンド検出・grammar ホットリロード
│   ├── command_executor.py  # Home Assistant REST API 呼び出し
│   ├── database.py          # SQLite CRUD（コマンド・応答・キャラクター管理）
│   ├── voicevox.py          # VoiceVox による WAV 事前合成
│   ├── admin.py             # 管理画面 Blueprint
│   ├── templates/admin/     # 管理画面テンプレート
│   ├── requirements.txt
│   └── Dockerfile
├── docker-compose.yml
├── data/
│   ├── cache/               # Whisper モデルキャッシュ（自動生成）
│   └── app/
│       ├── commands.db      # SQLite DB（自動生成）
│       └── responses/       # 事前合成 WAV ファイル（自動生成）
└── hass_config/             # Home Assistant 設定（自動生成）
```

---

## セットアップ

### 1. 環境変数の設定

`docker-compose.yml` を編集して以下を設定する。

```yaml
environment:
  - HA_URL=http://192.168.1.40:8123     # Home Assistant のホスト IP（サービス名不可）
  - HA_TOKEN=<長期アクセストークン>      # HA → プロフィール → セキュリティ で発行
  - HA_LIGHT_ENTITY=light.living_room   # HA のエンティティ ID に合わせて変更
  - HA_AC_ENTITY=climate.living_room
  - HA_PC_ENTITY=switch.pc
```

> `HA_TOKEN` が未設定でも起動は可能。Home Assistant への呼び出しのみスキップされる。

> `homeassistant` コンテナは `network_mode: host` のため Docker ネットワーク内から
> サービス名（`http://homeassistant:8123`）では到達できない。ホストの実 IP を指定すること。

### 2. 初回ビルドと起動

```bash
docker compose up -d --build
```

初回は VOSK モデル（約1GB）のダウンロードが走るため時間がかかる。
Whisper モデルは初回リクエスト時に自動ダウンロードされる。

### 3. 応答 WAV の生成

起動直後はコマンド・フォールバックに対応する WAV がない状態のため、管理画面で生成する。

```
http://<サーバーIP>:8000/admin
```

1. **キャラクター管理** でキャラクターを確認（初期データ「デフォルト」が作成済み）
2. **コマンド** → 各コマンドの編集画面で「全再合成」を実行
3. **フォールバック応答** で「全再合成」を実行
4. すべてのセルが ✅ になれば動作可能

---

## 日常操作

### 起動 / 停止

```bash
# 起動
docker compose up -d

# 停止
docker compose down

# voice サービスだけ再起動
docker compose restart voice
```

### ログ確認

```bash
# リアルタイムで流す
docker compose logs -f voice

# 直近100行
docker compose logs --tail=100 voice
```

### コードを変更したとき

```bash
# ビルドして再起動
docker compose up -d --build voice

# ダウンタイムを最小にしたい場合
docker compose build voice && docker compose up -d voice
```

`docker-compose.yml` の環境変数だけ変えた場合はビルド不要。

```bash
docker compose up -d voice
```

---

## 管理画面（`/admin`）

`http://<サーバーIP>:8000/admin` にアクセスする（認証なし・LAN 内運用想定）。

### コマンド管理

- コマンドの追加・編集・削除
- VOSK grammar（認識ワード）を複数登録可能
- 応答テキスト（ラベル）を複数登録 → キャラクターごとに WAV を管理
- grammar 変更後は画面上部の **「🔄 VOSK に反映」** を押すこと（再起動不要）

### フォールバック応答

- コマンド未検出時にランダム再生される応答を管理
- 複数登録するとランダムに選択される

### キャラクター管理

キャラクターごとに WAV の生成方法を設定できる。

| 合成タイプ | 説明 |
|---|---|
| **VoiceVox**（自動合成） | VoiceVox のスピーカー ID を指定。テキスト追加時に自動生成 |
| **手動アップロード** | VOCALOID・録音音声など任意の WAV をブラウザからアップロード |

- `is_active=1` のキャラクターがリクエスト時に使用される
- 複数キャラクターを登録しておき「アクティブ設定」で切り替え可能
- VoiceVox スピーカーを変更した場合は「全再合成」で WAV を更新する

---

## 初期コマンド一覧

DB に自動投入される初期データ。管理画面から自由に変更・削除可能。

| コマンド名 | 認識ワード | Home Assistant 操作 |
|---|---|---|
| ライトオン | ライト オン | `light.turn_on` |
| ライトオフ | ライト オフ | `light.turn_off` |
| 冷房オン | 冷房 オン | `climate.set_hvac_mode（cool）` |
| 暖房オン | 暖房 オン | `climate.set_hvac_mode（heat）` |
| エアコンオフ | エアコン オフ | `climate.turn_off` |
| 学習開始 | 学習 開始 | （HA 未連携・応答のみ） |
| パソコンつけて | パソコン つけて | `switch.turn_on` |

---

## モデルの配置

| モデル | 場所 | タイミング |
|---|---|---|
| VOSK `vosk-model-ja-0.22` | イメージ内 `/app/vosk-model-ja-0.22/` | Dockerfile ビルド時にダウンロード |
| Whisper `small` | `./data/cache/` にマウント | 初回リクエスト時に自動ダウンロード |

---

## API

| メソッド | パス | 説明 |
|---|---|---|
| `POST` | `/voice` | 16kHz モノラル WAV を受け取り応答 WAV を返す。`file` フィールドに WAV を添付 |
| `POST` | `/reload` | VOSK grammar をホットリロード（管理画面から呼ばれる） |
| `GET` | `/admin` | 管理画面トップ（コマンド一覧） |

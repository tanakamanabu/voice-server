# voice-server 設計ドキュメント

## システム全体像

```
[ラズパイ / speaker-remote]
  マイク → openwakeword → arecord → POST /voice (WAV)
                                            ↓
                                   [voice-server]
                                   vosk_detector
                                   （DBからgrammarロード）
                                       ↓
                          ┌─── コマンド検出あり ──────────────────┐
                          │                                      │
                   command_executor                        Whisper（汎用）
                  （DBからcommand取得）                           ↓
                       HA REST API                       エコー応答テキスト
                          │                                      │
                          └─────────────── response_text ────────┘
                                               ↓
                                  DBからランダムにWAV取得
                                  （事前合成済みファイル）
                                               ↓
                                       WAV をラズパイへ返す
                                               ↓
                                          aplay で再生

[Home Assistant]  ←  REST API  ←  command_executor
[VoiceVox]        ←  事前生成時のみ呼び出し（管理画面から）
```

---

## 実装スコープ

### 今回追加・変更するもの

| 機能 | 概要 |
|---|---|
| DBによるコマンド管理 | 現在ソースに直書きのコマンド定義をSQLiteへ移行 |
| VOSK grammar 1:多 | コマンドごとに複数の読み方・表記ゆれを登録可能 |
| 応答テキスト 1:多 | コマンドごとに複数の応答文を登録、実行時にランダム選択 |
| VoiceVox 事前合成 | 応答テキスト保存時にWAVを生成・保存。実行時はファイルをそのまま返す |
| 管理画面 | コマンド・grammar・応答テキストのCRUD操作をブラウザで行う |

### 変更しないもの

- speaker-remote 側のコード（WAVを送ってWAVを受け取るインターフェースは不変）
- VOSK / Whisper の音声認識処理の基本ロジック
- HA REST API の呼び出し方法

---

## データベース設計

### ER図

```
commands
  ├── command_grammars  (1:多)
  └── command_responses (1:多)
```

### テーブル定義

#### commands

コマンドの本体。HAサービス呼び出し情報を持つ。

| カラム | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT UNIQUE | コマンド識別名（例: ライトオン） |
| `ha_domain` | TEXT | HAサービスのドメイン（例: light）。NULL可（HA未連携コマンド用） |
| `ha_service` | TEXT | HAサービス名（例: turn_on）。NULL可 |
| `ha_entity_id` | TEXT | 操作対象エンティティID（例: light.living_room）。NULL可 |
| `ha_extra` | TEXT | 追加パラメータのJSON（例: `{"hvac_mode": "cool"}`）。デフォルト `{}` |
| `enabled` | INTEGER | 有効フラグ（1=有効、0=無効）。デフォルト 1 |
| `created_at` | TEXT | 作成日時（ISO8601） |
| `updated_at` | TEXT | 更新日時（ISO8601） |

#### command_grammars

VOSKが認識する読み方・表記ゆれ。1コマンドに複数登録可能。

| カラム | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK | |
| `command_id` | INTEGER FK | commands.id |
| `grammar` | TEXT | VOSKに渡すトークン（例: ライト オン）スペース区切り |

- `(command_id, grammar)` にUNIQUE制約

#### command_responses

応答テキストと事前合成済みWAVのパス。1コマンドに複数登録可能。

| カラム | 型 | 説明 |
|---|---|---|
| `id` | INTEGER PK | |
| `command_id` | INTEGER FK | commands.id |
| `text` | TEXT | 応答テキスト（例: はーい！ライトつけます！） |
| `wav_path` | TEXT | 事前合成済みWAVファイルのパス。NULL = 未生成 |
| `generated_at` | TEXT | WAV生成日時。NULL = 未生成 |

---

## VoiceVox 連携

### 事前合成フロー

管理画面で応答テキストを保存したタイミングで合成を実行する。

```
POST /audio_query?text=<text>&speaker=<speaker_id>
  → audio_query (JSON)

POST /synthesis?speaker=<speaker_id>
  body: audio_query
  → WAV bytes

保存先: /app/responses/<response_id>.wav
DBのwav_path・generated_atを更新
```

### 実行時フロー

```python
response = db.get_random_response(command_id)
if response.wav_path:
    return send_file(response.wav_path)   # 合成済みWAVをそのまま返す
else:
    # フォールバック: リアルタイム合成（未生成の場合）
    wav = voicevox.synthesize(response.text)
    return wav
```

### VoiceVox スピーカーID

`GET http://voicevox:50021/speakers` で一覧取得可能。  
デフォルトは環境変数 `VOICEVOX_SPEAKER_ID`（未設定時: `1` = 四国めたん）で指定。  
管理画面でレスポンスごとに個別指定もできるようにする（後述）。

---

## 管理画面設計

### URLルーティング

| メソッド | パス | 説明 |
|---|---|---|
| GET | `/admin` | コマンド一覧 |
| GET/POST | `/admin/commands/new` | コマンド新規作成 |
| GET/POST | `/admin/commands/<id>/edit` | コマンド編集 |
| POST | `/admin/commands/<id>/delete` | コマンド削除 |
| GET/POST | `/admin/commands/<id>/grammars/new` | grammar追加 |
| POST | `/admin/grammars/<id>/delete` | grammar削除 |
| GET/POST | `/admin/commands/<id>/responses/new` | 応答テキスト追加（保存時にWAV自動生成） |
| POST | `/admin/responses/<id>/delete` | 応答削除（WAVファイルも削除） |
| POST | `/admin/responses/<id>/regenerate` | WAV再生成 |
| POST | `/admin/reload` | VOSKgrammarのリロード（再起動不要） |

### 画面構成

```
/admin（コマンド一覧）
┌─────────────────────────────────────────────┐
│ コマンド一覧          [+ 新規コマンド]        │
├────────────┬──────────┬───────────┬──────────┤
│ ライトオン  │ 有効     │ grammar 2 │ 応答 3件 │ [編集][削除]
│ 冷房オン   │ 有効     │ grammar 1 │ 応答 2件 │ [編集][削除]
└────────────┴──────────┴───────────┴──────────┘

/admin/commands/<id>/edit（コマンド詳細・編集）
┌─────────────────────────────────────────────┐
│ コマンド名: ライトオン                         │
│ HA設定: light / turn_on / light.living_room  │
├─────────────────────────────────────────────┤
│ 認識ワード（grammar）       [+ 追加]           │
│  - "ライト オン"            [削除]             │
│  - "でんき つけて"          [削除]             │
├─────────────────────────────────────────────┤
│ 応答テキスト                [+ 追加]           │
│  - "ライトをつけましたよ♪"  [再生成][削除]     │
│  - "はーい！"               ⚠️未生成  [生成][削除] │
└─────────────────────────────────────────────┘
```

---

## ファイル構成（変更後）

```
app/
├── main.py                  変更: espeak削除・VoiceVox WAV返却
├── vosk_detector.py         変更: DBからgrammarロード・リロード対応
├── command_executor.py      変更: DBからcommand・random response取得
├── database.py              新規: SQLite操作（初期化・CRUD）
├── voicevox.py              新規: VoiceVox API呼び出し・WAV事前生成
├── admin.py                 新規: 管理画面Blueprint
├── templates/
│   └── admin/
│       ├── index.html       コマンド一覧
│       ├── command_form.html コマンド作成・編集
│       └── response_form.html 応答テキスト追加
├── static/                  新規: CSS等（Bootstrap CDN使用で最小限）
└── responses/               新規: 事前生成WAV置き場（Dockerボリュームに含める）
```

---

## 環境変数（追加分）

| 変数 | デフォルト | 説明 |
|---|---|---|
| `VOICEVOX_URL` | `http://voicevox:50021` | VoiceVox エンジンURL |
| `VOICEVOX_SPEAKER_ID` | `1` | デフォルトスピーカーID |
| `DB_PATH` | `/app/data/commands.db` | SQLiteファイルパス |
| `RESPONSES_DIR` | `/app/responses` | 事前生成WAV保存ディレクトリ |

`DB_PATH` と `RESPONSES_DIR` は `docker-compose.yml` のボリューム `./data:/app/data` に含める。

---

## 実装順序

### Step 1: DB層とスキーマ
`database.py` の作成。テーブル定義・CRUD関数・起動時の初期データ投入（現在のハードコードコマンドをSQLiteへ移行）。

### Step 2: vosk_detector / command_executor のDB参照切り替え
`vosk_detector.py` をDBからgrammarを読むように変更。`command_executor.py` をDBからcommandとrandom responseを取得するように変更。この時点でespeak→VoiceVoxリアルタイム合成へ切り替え。

### Step 3: VoiceVox 事前合成
`voicevox.py` の作成。`POST /audio_query` → `POST /synthesis` → WAVファイル保存のフロー実装。

### Step 4: 管理画面
`admin.py` とHTMLテンプレートの作成。CRUD + WAV生成ボタン + grammarリロードボタン。

---

## 未決事項

- Whisperの汎用応答（コマンド未検出時のエコー）もVoiceVoxで合成するか → リアルタイム合成になるので遅延が発生する。espeak残留 or 許容するか要確認
- 管理画面の認証 → 社内LAN内のみのためなし（必要になれば Basic認証を追加）
- VOSKのgrammarリロードタイミング → 管理画面の「反映」ボタン押下時 or 変更を検知して自動リロード

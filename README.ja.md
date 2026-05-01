# TimelineForAudio

TimelineForAudio は、固定された入力ディレクトリ内の音声を読み取り、元音声の時間軸を保ったまま、話者ラベルと phone token を記録するローカル CLI ツールです。

[English README](README.md) | [Spec Checklist](docs/SPEC_CHECKLIST.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [License](LICENSE)

## 方針

Windows では PowerShell の `start.ps1` / `start.bat` を正面玄関として使い、Docker container 内の worker を起動します。CLI 操作は `cli.ps1` を使います。

この製品は、意味解釈や読みやすい本文復元は行いません。責務は、後段の LLM や別製品が扱いやすいように、音声を時間情報付きの構造データへ変換するところまでです。

主成果物は次です。

- `conversion-info.json`
- `timeline.json`

処理用の正規化音声、発話候補マップ、モデル実行用の一時ファイルは、マスター出力には残しません。
`<temporary app data>/runs/<run-id>/RUN_PERFORMANCE.json` などの run 単位のファイルは、CLI の状態確認とトラブル調査用です。

## 処理の流れ

1. 入力ディレクトリを scan する
2. 変化がない音声を skip する
3. 音声を 16kHz mono WAV に正規化する
4. `ffmpeg silencedetect` で発話候補区間を作る
5. `pyannote/speaker-diarization-community-1` で話者 turn を作る
6. 発話候補区間を短い単位に分け、ZIPA large ONNX バックエンドで phone token を抽出する
7. 話者 turn と phone token turn を時間で合わせる
8. `speaker + time + phone_tokens` の timeline JSON と変換情報 JSON を保存する

長い音声を一つの大きな推論として処理しないため、大きなファイルでも途中失敗時の手戻りを小さくできます。

話者は `SPEAKER_00`、`SPEAKER_01` のような機械ラベルで扱います。実名、本人性、性別、年齢、属性は推測しません。

## 必要なもの

- Docker Desktop
- Docker engine が起動していること
- 初回モデル取得用のインターネット接続
- Hugging Face token
- `pyannote/speaker-diarization-community-1` の利用承認
- GPU mode を使う場合は NVIDIA GPU と Docker GPU 環境

通常の CLI は Docker container 内だけで実行します。ホストから直接 `python -m timeline_for_audio_worker ...` を実行する運用は通常許可していません。

## 最短実行

repo ルートで実行します。

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 items refresh
```

処理対象を確認するだけなら次を使います。

```powershell
.\cli.ps1 files list
```

同じファイルを強制的に再処理する場合だけ、次を使います。

```powershell
.\cli.ps1 items refresh --reprocess-duplicates
```

## ローカル設定

永続設定は repo ルートに保存します。

- `settings.example.json`: Git 管理する設定例
- `settings.json`: ローカル設定。Git 管理しない

現在の設定例では、入力ディレクトリは `C:\TimelineData\Audio\`、マスター出力ディレクトリは `C:\TimelineData\AudioMaster\` です。
Hugging Face token も `settings.json` に保存します。

```powershell
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu
```

ファイルが同じかどうかは、次で判定します。

- `source hash`
- `generation signature`
- `source file identity`

ファイル名や入力ディレクトリ内の相対パスが変わった場合は、同じ音声内容でも別ファイルとして扱います。ファイル名には会議名など後段で有用な情報が含まれることがあるためです。

## 主なコマンド

- `start.ps1` / `start.bat`: Docker worker を起動する
- `cli.ps1` / `cli.bat`: Docker worker 内で CLI を実行する
- `stop.ps1` / `stop.bat`: Docker worker を停止する
- `uninstall.ps1` / `uninstall.bat`: Docker container / image / volume を削除する
- `settings status`
- `settings init`
- `settings inputs list/add/remove/clear`
- `settings master show/set`
- `models list`
- `files list`
- `files scan`
- `items list`
- `items refresh`
- `items refresh --max-items <N>`
- `items remove`
- `items download`
- `runs list`
- `runs show`

例:

```powershell
.\cli.ps1 files list --json
.\cli.ps1 items list --json
.\cli.ps1 items refresh --max-items 3 --json
.\cli.ps1 items remove --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --dry-run --json
.\cli.ps1 items download --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --json
.\cli.ps1 items download --all --json
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
```

`items refresh` はデフォルトで対象を全件キューに入れます。実データ確認や失敗範囲を小さくしたい場合だけ、`items refresh --max-items 1` のように件数を指定します。

`items remove` は、元の音声ファイルを削除しません。指定した `item_id` に対応する管理データと生成物だけを削除し、次回 `items refresh` では未作成として再処理対象にします。削除前確認には `--dry-run` を使えます。

CLI を管理 UI や別プロダクトから呼び出す場合は、返却 JSON の詳細を [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md) で確認してください。

使用モデルと確認先を一覧にする場合は次を使います。

```powershell
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

`--include-remote` は Hugging Face API から license / gated / tags などを取得します。利用条件の最終確認は、出力される Hugging Face のモデルページで行ってください。

## CLI 構造

CLI は、入力ファイル、管理 item、実行 run、固定設定を分けて扱います。

### コマンド群

| コマンド群 | 役割 |
|---|---|
| `files` | 入力ディレクトリに今ある実ファイルを確認する |
| `items` | TimelineForAudio が管理する解析対象と生成物を扱う |
| `runs` | 実行単位を確認する。診断・開発者向け |
| `settings` | 固定設定を管理する。入力元は複数、マスター保存先は 1 箇所 |

主な操作:

```powershell
.\cli.ps1 files list
.\cli.ps1 items list
.\cli.ps1 items refresh
.\cli.ps1 items remove --item-id <ITEM_ID_1>,<ITEM_ID_2>
.\cli.ps1 items download --item-id <ITEM_ID_1>,<ITEM_ID_2>
.\cli.ps1 items download --all
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
```

`settings` は、複数の入力元と 1 つのマスター保存先を明確に分けます。

```powershell
.\cli.ps1 settings inputs add "C:\TimelineData\Audio\"
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs remove input-a7f3k9
.\cli.ps1 settings master set "C:\TimelineData\AudioMaster\"
.\cli.ps1 settings master show
```

### `files` と `items` の分離

`files` は、入力ディレクトリに現在存在する音声ファイルを見るためのコマンドです。過去に存在したが今は消えているファイルや、すでに生成済みの管理データは扱いません。

`items` は、TimelineForAudio が管理している解析対象です。元ファイルが入力ディレクトリから消えていても、生成済みの item は管理対象として残る可能性があります。そのため、生成物の削除やダウンロードは `files` ではなく `items` で扱います。

`items remove` は、元の音声ファイルを削除しません。指定した `item_id` に対応する管理データと生成物だけを削除します。複数の `item_id` をカンマ区切りで指定できます。入力ディレクトリに元ファイルが残っていれば、次回 `items refresh` で再作成されます。

`items download` は、指定した `item_id` の生成物を取得します。複数の `item_id` を指定した場合は、まとめて取得します。`items download --all` を使うと、現在利用可能な全 item をまとめて取得します。`outputs` という別コマンド群は作らず、生成物は item の一部として扱います。

### 廃止した旧コマンド

| 旧コマンド | 現在の扱い | 意図 |
|---|---|---|
| `settings input-root` | `settings inputs` | 入力元は複数あるため、複数形で扱う |
| `settings output-root` | `settings master` | マスター保存先は 1 箇所なので単数で扱う |
| `scan` | `files scan` | 入力ファイル確認系として `files` に寄せる |
| `files delete-generated` | `items remove --item-id <ITEM_ID>` | 生成物削除は実ファイルではなく管理 item に対して行う |
| `refresh` | `items refresh` | refresh 対象は管理 item なので `items` 配下に置く |
| `runs archive` | 削除 | run 単位のダウンロードは提供しない |
| `process-run` | 内部コマンド扱い | 通常ユーザー向けには隠す |
| `daemon` | 内部コマンド扱い | Docker worker 起動用であり、通常ユーザー向けには隠す |

### 入力ディレクトリ管理

入力ディレクトリは、ユーザーが毎回細かい識別子を考えるものではありません。「追加」「一覧」「削除」だけのシンプルな操作にしています。

```powershell
.\cli.ps1 settings inputs add "C:\TimelineData\Audio\"
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs remove input-a7f3k9
```

方針:

- `add` 時に ID を入力させない
- ID は `input-a7f3k9` のような短いランダム値を自動発行する
- ID はユーザー概念ではなく、削除や個別 refresh のための操作用識別子として扱う
- `display-name` は基本不要にする
- `enable` / `disable` は使わない。使わない入力元は削除する
- path を変更したい場合は、既存の入力元を削除して、新しい path を追加する

`source_file_identity` についても、将来的には入力元 ID ではなく、入力ディレクトリのパス由来情報と相対パスをもとに作る方向を検討します。これにより、入力元 ID を再発行しても、同じディレクトリと同じ相対パスなら同じファイルとして扱いやすくなります。

例:

```text
root-b4c91a:20220401020001.m4a
```

この見直しは再利用判定に影響するため、コマンド名の変更とは別に、破壊的変更として扱います。

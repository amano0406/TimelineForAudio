# TimelineForAudio

`TimelineForAudio` は、固定された入力ディレクトリ内の音声を読み取り、話者ラベル付きの phone token timeline を更新するローカル Docker-first CLI ツールです。

[English README](README.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [License](LICENSE)

この製品は CLI 専用です。Web UI はありません。表に出る面は、入力音声 path、ローカル設定、マスター成果物、ダウンロード ZIP、CLI JSON 出力に限定します。run 状態、ログ、モデル cache、一時ファイルは製品内部の管理対象です。

## できること

- 固定された入力ディレクトリから音声ファイルを読む
- `source hash`、`source file identity`、`generation signature` が変わらないファイルを skip する
- 元音声の時間軸を維持したまま、発話候補区間を短い単位で処理する
- `pyannote/speaker-diarization-community-1` で話者分離する
- ZIPA large ONNX backend で phone token を抽出する
- 解析済み音声ごとに master item directory を作る
- 必要に応じて handoff ZIP を作る
- 利用モデルの一覧を出し、license や利用条件確認に使える情報を返す

## しないこと

- Web UI は提供しない
- 可読テキストには復元しない
- 意味の要約はしない
- 話者の実名、本人性、年齢、性別、属性は推測しない
- 元の音声ファイルは変更しない
- 処理途中の scratch file を master output に置かない
- run directory をユーザー向け download artifact として扱わない

## 処理の流れ

1. 設定済み入力ディレクトリから音声ファイルを読む
2. 元ファイルを変更せず、処理用に音声を正規化する
3. 発話候補区間を検出し、元音声から見た相対時刻を保持する
4. 話者分離を行う
5. 発話候補区間から phone token を抽出する
6. 話者 turn、timestamp、phone token を `timeline.json` に統合する
7. source、model、runtime、処理手順を `convert_info.json` に保存する

長時間音声を ZIPA に一つの大きな推論として渡しません。発話候補区間を内部で分割し、結果を元の時間軸へ戻します。

## Settings

通常の Docker Compose 運用では、repo 直下のローカル設定ファイルを使います。

```text
C:\apps\TimelineForAudio\settings.json
```

Git 管理するテンプレートは次です。

```text
C:\apps\TimelineForAudio\settings.example.json
```

`settings.json` は Git 管理しません。存在しない場合は `settings.example.json` から作成します。

設定例:

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    "C:\\TimelineData\\input-audio\\"
  ],
  "outputRoot": "C:\\TimelineData\\audio",
  "huggingfaceToken": "",
  "computeMode": "cpu"
}
```

ユーザーが設定する項目:

| Key | 意味 |
|---|---|
| `inputRoots` | 固定入力ディレクトリ。各行は path 文字列 |
| `outputRoot` | 固定の master artifact directory |
| `huggingfaceToken` | model access 用のローカル Hugging Face token |
| `computeMode` | `cpu` または `gpu` |

対応音声拡張子などの製品固定値は runtime defaults 側で管理し、ユーザー設定には含めません。

## Output Contract

Master output:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

Download ZIP:

```text
README.md
items/
  <item-id>/
    convert_info.json
    timeline.json
```

`timeline.json` は最終的な構造化音声 timeline です。

```json
{
  "schema_version": 1,
  "artifact_type": "timeline",
  "source": {},
  "pipeline": {},
  "turns": [
    {
      "start_sec": 12.34,
      "end_sec": 15.67,
      "speaker": "SPEAKER_00",
      "phone_tokens": "..."
    }
  ]
}
```

`convert_info.json` には、source fingerprint、model/runtime metadata、processing-flow metadata、counts、output file names を入れます。

## Storage Model

| 場所 | 管理者 | 永続 | 表に見える | 用途 |
|---|---|---:|---:|---|
| `settings.json` | ユーザー / ローカルPC | Yes | Yes | 固定入力元、出力先、token、compute mode |
| `outputRoot` | ユーザー / 後段製品 | Yes | Yes | master item artifacts |
| `app-data` Docker volume | TimelineForAudio | Yes | No | run state、status、logs、ETA history、catalog index |
| `cache-data` Docker volume | TimelineForAudio / model libraries | Yes | No | Hugging Face、Transformers、Torch、model cache |
| container 内 `/tmp/...` | TimelineForAudio | No | No | 一時 staging と scratch work |

内部 storage は製品側で変更してよい領域です。後段製品が依存すべきなのは、master output、download ZIP、CLI JSON contract です。

## CLI Usage

repo ルートで実行します。

```powershell
cd C:\apps\TimelineForAudio
```

Windows では `*.ps1` を正面入口にします。`*.bat` は PowerShell script を直接起動できない環境向けの薄い互換ラッパーで、別挙動を持たせません。

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu

.\cli.ps1 files list --json
.\cli.ps1 files list --page 1 --page-size 50 --json
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --max-items 3 --json
.\cli.ps1 items list --json
.\cli.ps1 items list --page 1 --page-size 50 --json
.\cli.ps1 items remove --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --dry-run --json
.\cli.ps1 items download --json
.\cli.ps1 items download --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --json
.\cli.ps1 runs list --json
.\cli.ps1 runs show --run-id <RUN_ID> --json
```

外部アプリケーションからの呼び出し例:

```cmd
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 settings status --json
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 files list --json
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 items refresh --json
```

WSL や Codex から確認する場合は、Windows command host 経由で呼び出します。

```bash
cmd.exe /c "cd /d C:\apps\TimelineForAudio && powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File cli.ps1 settings status --json"
```

補足:

- `items refresh` は、変更された対象をデフォルトで全件 queue に入れます。
- 小さく試す場合は `items refresh --max-items <N>` を使います。
- 同じファイルを意図的に再処理する場合だけ `items refresh --reprocess-duplicates` を使います。
- `items remove` は管理 item と生成物だけを削除します。元音声は削除しません。
- `runs` は診断用です。run directory は製品内部の runtime file です。
- CLI JSON 出力の詳細は [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md) を参照してください。

使用モデルの確認:

```powershell
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

`--include-remote` は Hugging Face API から license、gated、tag などを取得します。利用条件の最終確認は、出力される upstream model page で行ってください。

## Docker Compose

通常の Windows 運用では、Docker command を直接打たず、`start.ps1`、`cli.ps1`、`stop.ps1` を使います。

Compose project name:

```text
timeline-for-audio
```

worker service は Python CLI を実行します。browser port は公開しません。

Docker resources:

- `app-data`: 製品内部の runtime data
- `cache-data`: model と library cache
- input roots: `settings.json` から生成する read-only bind mount
- `outputRoot`: `settings.json` から生成する writable bind mount

GPU mode は、`settings.json` が `"computeMode": "gpu"` で、PowerShell から NVIDIA GPU を確認できる場合だけ `docker-compose.gpu.yml` を使います。

worker 停止:

```powershell
.\stop.ps1
```

Docker resource の削除:

```powershell
.\uninstall.bat
```

`uninstall.bat` は既定では `app-data`、`cache-data`、`settings.json` を残します。削除したい場合だけ、削除オプションを明示して使います。

## Testing

通常利用で host Python CLI を直接実行することは許可していません。テスト時だけ明示的な開発用 override を使います。

Unit tests:

```bash
TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI=1 \
PYTHONPATH=/mnt/c/apps/TimelineForAudio/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForAudio/worker/tests -v
```

Docker checks:

```powershell
.\start.ps1
.\cli.ps1 settings status --json
.\cli.ps1 files list --json
.\cli.ps1 items refresh --max-items 1 --json
.\cli.ps1 items list --json
```

ローカル `cli.ps1` download smoke test:

```powershell
.\scripts\test-local-cli-download.ps1
```

Python checks の後にこの smoke test も含める場合:

```powershell
.\scripts\lint.ps1 -IncludeLocalCliDownload
```

## Repo Layout

```text
configs/
docker/
docs/
scripts/
worker/
cli.ps1
start.ps1
stop.ps1
uninstall.ps1
settings.example.json
```

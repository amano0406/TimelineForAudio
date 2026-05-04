# TimelineForAudio

`TimelineForAudio` は、固定された入力ディレクトリ内の音声を Docker 上で解析し、話者・時刻・phone token を持つ `timeline.json` と `convert_info.json` を維持する CLI 製品です。

[English README](README.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [License](LICENSE)

## README の役割

この README は、初回確認と通常運用の入口です。

- 何をする製品かを短く把握する
- Windows PowerShell から起動・設定・変換・取得する
- どの成果物に依存すればよいかを確認する
- 詳細仕様が必要な場合に `docs/` へ進む

CLI の全返却仕様、pipeline 詳細、安定性チェック、release 手順は README ではなく `docs/` に分けています。

## Timeline 系サブ製品としての位置づけ

`TimelineForAudio` は、最終的に人が読む文章を作る製品ではなく、音声を後段の Timeline 製品や LLM が扱いやすい構造データへ変換するサブ製品です。

中心に置くものは、元音声の時間軸です。長い録音の中で「いつ、誰に相当する話者が、どのような音を発したか」を、後から再利用できる JSON として残します。

この製品では意味解釈をしません。話者の実名も推測しません。可読テキストへの復元、要約、会話内容の解釈は、`timeline.json` を受け取る後段の製品や LLM の責務です。

そのため、この製品の公開面は小さく保ちます。入力ディレクトリ、`settings.json`、master artifacts、download ZIP、CLI JSON output だけを安定した面として扱い、run 状態、ログ、cache、一時ファイルは内部実装として扱います。

## 製品の責務

この製品が行うこと:

- 設定済み入力ディレクトリから音声ファイルを読む
- 変更がない音声は skip する
- 元音声の時間軸を維持する
- `pyannote/speaker-diarization-community-1` で話者分離する
- ZIPA large ONNX backend で phone token を抽出する
- `timeline.json` と `convert_info.json` を master 出力に保存する
- 必要に応じて downstream 用 ZIP を作る

この製品が行わないこと:

- Web UI は提供しない
- 可読テキストには復元しない
- 要約や意味解釈はしない
- 話者の実名、本人性、年齢、性別、属性は推測しない
- 元音声ファイルは変更しない
- run directory や scratch file をユーザー向け成果物として扱わない

## 前提

- Windows では PowerShell が正面入口です。
- Docker Desktop が必要です。
- Hugging Face token が必要です。
- 話者分離には `pyannote/speaker-diarization-community-1` の利用承認が必要です。
- GPU mode は任意です。NVIDIA GPU と Docker GPU support が使える場合だけ有効にします。

## Quick Start

repo ルートで実行します。

```powershell
cd C:\apps\TimelineForAudio
```

1. Docker worker を起動します。

```powershell
.\start.ps1
```

2. 設定ファイルがなければ作成します。

```powershell
.\cli.ps1 settings init --json
```

3. token と処理 mode を保存します。

```powershell
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json
```

CPU で使う場合:

```powershell
.\cli.ps1 settings save --compute-mode cpu --json
```

4. 入力ディレクトリと master 出力先を確認します。

```powershell
.\cli.ps1 settings inputs list --json
.\cli.ps1 settings master show --json
```

5. 音声ファイルを確認し、変換します。

```powershell
.\cli.ps1 files list --json
.\cli.ps1 items refresh --json
```

6. 生成物を確認し、ZIP を作成します。

```powershell
.\cli.ps1 items list --json
.\cli.ps1 items download --json
```

## Settings

通常運用では、repo 直下のローカル設定ファイルを使います。

```text
C:\apps\TimelineForAudio\settings.json
```

`settings.json` は Git 管理しません。テンプレートは `settings.example.json` です。

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

| Key | 意味 |
|---|---|
| `inputRoots` | 固定入力ディレクトリ。配列で path 文字列を並べる |
| `outputRoot` | master 成果物を保存する固定ディレクトリ |
| `huggingfaceToken` | model access 用の Hugging Face token |
| `computeMode` | `cpu` または `gpu` |

対応音声拡張子などの製品固定値は runtime defaults 側で管理し、ユーザー設定には含めません。

## Output

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

`timeline.json` が最終成果物です。話者、音声相対時刻、絶対時刻が取れる場合の時刻、phone token を保持します。

`convert_info.json` は変換情報です。source fingerprint、model/runtime metadata、processing-flow metadata、counts、output file names を保持します。

音声ファイルそのものは master output や download ZIP に含めません。

## よく使う CLI

| 目的 | コマンド |
|---|---|
| 起動 | `.\start.ps1` |
| 停止 | `.\stop.ps1` |
| 設定状態 | `.\cli.ps1 settings status --json` |
| 入力追加 | `.\cli.ps1 settings inputs add "C:\TimelineData\input-audio\" --json` |
| master 出力先変更 | `.\cli.ps1 settings master set "C:\TimelineData\audio" --json` |
| 入力音声一覧 | `.\cli.ps1 files list --json` |
| 変更分を変換 | `.\cli.ps1 items refresh --json` |
| 小さく試す | `.\cli.ps1 items refresh --max-items 3 --json` |
| 生成物一覧 | `.\cli.ps1 items list --json` |
| 生成物削除 | `.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json` |
| ZIP 作成 | `.\cli.ps1 items download --json` |
| 利用モデル確認 | `.\cli.ps1 models list --json` |

CLI JSON の詳細は [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md) を参照してください。

`runs` は診断用です。run directory は製品内部の runtime file であり、ユーザー向け成果物ではありません。

## Docker と storage

通常の Windows 運用では、Docker command を直接打たず、`start.ps1`、`cli.ps1`、`stop.ps1` を使います。

| 場所 | 表に見える | 用途 |
|---|---:|---|
| `settings.json` | Yes | 固定入力元、出力先、token、compute mode |
| `outputRoot` | Yes | master item artifacts |
| `app-data` Docker volume | No | run state、status、logs、catalog index |
| `cache-data` Docker volume | No | Hugging Face、Transformers、Torch、model cache |
| container 内 `/tmp/...` | No | 一時 staging と scratch work |

`uninstall.ps1` は既定では `app-data`、`cache-data`、`settings.json` を残します。削除したい場合だけ削除オプションを明示します。

## Testing

通常利用で host Python CLI を直接実行することは許可していません。テスト時だけ明示的な開発用 override を使います。

通常チェック:

```powershell
.\scripts\lint.ps1 -IncludeLocalCliDownload -IncludeOperationalSmoke
```

実モデルで full pipeline を確認したい場合:

```powershell
.\scripts\test-operational.ps1 -UseRealModels -SourceAudioPath "C:\TimelineData\input-audio\sample.mp3" -KeepOutput
```

この実モデル smoke test は、入力と出力を隔離された test workspace に向けます。通常の `settings.json` は変更しません。

## Docs

| 文書 | 役割 |
|---|---|
| [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md) | CLI JSON 返却仕様 |
| [docs/PIPELINE.md](docs/PIPELINE.md) | pipeline と artifact の詳細 |
| [docs/OPERATIONAL_STABILITY.ja.md](docs/OPERATIONAL_STABILITY.ja.md) | 安定性チェックリスト |
| [docs/SECURITY_AND_SAFETY.md](docs/SECURITY_AND_SAFETY.md) | 安全境界と削除系の注意 |
| [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md) | 利用モデルと runtime 補足 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | third-party notices |
| [docs/MANUAL_RELEASE.md](docs/MANUAL_RELEASE.md) | 手動 release 手順 |

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

# TimelineForAudio

TimelineForAudio は、固定された入力ディレクトリ内の音声を読み取り、元音声の時間軸を保ったまま、話者ラベルと音響単位を記録するローカル CLI ツールです。

[English README](README.md) | [Spec Checklist](docs/SPEC_CHECKLIST.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [License](LICENSE)

## 方針

Web UI はありません。Windows では PowerShell の `cli.ps1` を正面玄関として使い、実処理は Docker container 内の worker が行います。

この製品は、意味解釈や読みやすい本文復元は行いません。責務は、後段の LLM や別製品が扱いやすいように、音声を時間情報付きの構造データへ変換するところまでです。

主成果物は次です。

- `timeline/speaker-acoustic-units-timeline.json`
- `timeline/speaker-acoustic-units-timeline.md`
- `ai-raw/speaker-turns.raw.json`
- `ai-raw/acoustic-units.raw.json`
- `segments/speech-candidates.json`
- `source/source-record.json`

## 処理の流れ

1. 入力ディレクトリを scan する
2. 変化がない音声を skip する
3. 音声を 16kHz mono WAV に正規化する
4. `ffmpeg silencedetect` で発話候補区間を作る
5. `pyannote/speaker-diarization-community-1` で話者 turn を作る
6. ZIPA 300M 系バックエンドで音響単位を抽出する
7. 話者 turn と音響単位 turn を時間で合わせる
8. `speaker + time + acoustic_units` の timeline JSON を保存する

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
.\cli.ps1 refresh
```

処理対象を確認するだけなら次を使います。

```powershell
.\cli.ps1 scan
```

同じファイルを強制的に再処理する場合だけ、次を使います。

```powershell
.\cli.ps1 refresh --reprocess-duplicates
```

## ローカル設定

永続設定は repo ルートに保存します。

- `settings.example.json`: Git 管理する設定例
- `settings.json`: ローカル設定。Git 管理しない

現在の設定例では、入力ディレクトリは `C:\TimelineData\Audio\`、マスター出力ディレクトリは `C:\TimelineData\AudioMaster\` です。

ファイルが同じかどうかは、次で判定します。

- `source hash`
- `generation signature`
- `source file identity`

ファイル名や入力ディレクトリ内の相対パスが変わった場合は、同じ音声内容でも別ファイルとして扱います。ファイル名には会議名など後段で有用な情報が含まれることがあるためです。

## 主なコマンド

- `settings status`
- `settings init`
- `settings input-root list/add/remove/enable/disable/clear`
- `settings output-root list/set`
- `scan`
- `refresh`
- `runs list`
- `runs show`
- `runs archive`
- `evaluate`

例:

```powershell
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
.\cli.ps1 runs archive --run-id <RUN_ID>
.\cli.ps1 evaluate --run-id <RUN_ID> --artifact-kind timeline --reference ".\references\case-001.json" --json
```

# TimelineForAudio

TimelineForAudio は、音声ファイルを IPA-first の成果物へ変換するローカル CLI ツールです。

[English README](README.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [License](LICENSE)

## 現在の方針

Web UI は削除しました。対応する入口は Python worker CLI です。

主な成果物はこれまでと同じです。

- `IPA.md`
- `Readable Text.md`
- IPA または Readable Text の ZIP

export ZIP には元の音声ファイルは含めません。

## できること

CLI では次を実行できます。

- ローカル設定の確認と保存
- 話者分離用の Hugging Face token 保存
- 音声ファイルから job 作成
- ローカル処理の実行
- job 一覧と詳細確認
- 完了 job から IPA ZIP または Readable Text ZIP を作成

処理の流れは次です。

1. 音声を正規化する
2. 文字起こし用の中間テキストを作る
3. 可能なら話者 turn を合わせる
4. turn 単位の IPA を canonical intermediate として作る
5. 必要なら IPA と文脈から可読テキストを復元する
6. 成果物と ZIP を出力する

## 必要なもの

- Python 3.11+
- PATH 上の FFmpeg
- 初回モデル取得用のインターネット接続
- 話者分離を使う場合は Hugging Face token
- GPU mode を使う場合は NVIDIA GPU 環境

Docker worker 用ファイルは残していますが、通常は直接 CLI を使うのが一番単純です。

## 最短実行

repo ルートで実行します。

```powershell
$env:PYTHONPATH=".\worker\src"
python -m timeline_for_audio_worker settings status
python -m timeline_for_audio_worker settings save --language ja --compute-mode cpu
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3"
python -m timeline_for_audio_worker jobs list
```

話者分離を使う場合:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m timeline_for_audio_worker settings save --token hf_xxx --terms-confirmed
```

IPA だけ作る場合:

```powershell
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3" --ipa-only
```

可読テキスト復元用の補足を渡す場合:

```powershell
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3" --language ja --supplemental-context-file ".\context.txt"
```

## 主なコマンド

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

例:

```powershell
python -m timeline_for_audio_worker jobs show --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
python -m timeline_for_audio_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa
python -m timeline_for_audio_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind readable-text
```

## ローカルデータ

既定の保存先:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix 系環境: `~/.timeline-for-audio`

必要なら環境変数で変更できます。

- `TIMELINE_FOR_AUDIO_APPDATA_ROOT`
- `TIMELINE_FOR_AUDIO_OUTPUTS_ROOT`
- `TIMELINE_FOR_AUDIO_UPLOADS_ROOT`

Hugging Face token は app data root 配下の `secrets/huggingface.token` に保存します。

## Docker Worker

`start.bat` と `start.command` は worker container を build / 起動するだけです。ブラウザは開きません。

```powershell
.\start.bat
```

GPU worker overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d worker
```

## 対応入力形式

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`

実際の decode は runtime の FFmpeg に依存します。

## ZIP 出力

IPA ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `ipa/<captured-datetime>.md`

Readable Text ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `readable-text/<captured-datetime>.md`

失敗時は failure report や worker log も含まれます。

## テスト

worker test:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

lint:

```powershell
.\scripts\lint.ps1
```

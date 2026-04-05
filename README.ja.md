# audio2timeline

手元の音声ファイルを、レビューしやすく、検索しやすく、ChatGPT などの LLM に渡しやすいタイムライン Markdown パッケージへ変換するローカルツールです。

[English README](README.md) | [サンプルタイムライン](docs/examples/sample-timeline.ja.md) | [第三者ライセンス](THIRD_PARTY_NOTICES.md) | [モデルと実行環境メモ](MODEL_AND_RUNTIME_NOTES.md) | [セキュリティと安全性](docs/SECURITY_AND_SAFETY.md) | [ライセンス](LICENSE)

## 概要

- local-first の desktop-style tool
- `video2timeline` とは別の、音声専用アプリ
- 主運用パスは Windows + Docker Desktop
- 不特定多数向けの導入簡略化より、手元での実運用を優先
- 話者分離には `pyannote/speaker-diarization-community-1` を使用

## 現在の機能

- 対応入力形式: `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`
- ファイル選択 / ディレクトリ選択の upload-first job 作成
- `faster-whisper` による文字起こし
- `pyannote` による optional な話者分離
- 次を使った deterministic transcript normalization
  - ASR initial prompt
  - glossary ベースの表記統一
- 次の audio feature summary
  - pause / silence
  - loudness
  - speaking rate
  - pitch
  - overlap / interruption
  - heuristic な speaker confidence
  - heuristic な diarization quality
- `source hash` と `conversion signature` の両方を使う duplicate 判定
- rerun with same settings
- rerun with current settings
- ZIP export
- `FAILURE_REPORT.md` と `logs/worker.log` を含む failure artifact

## 出力物

完了した job では、アイテムごとの Markdown artifact と ZIP handoff package を出力します。

典型的な ZIP の中身:

```text
audio2timeline-export.zip
  README.html
  TRANSCRIPTION_INFO.md
  timelines/
    2026-03-25 14-47-14.md
  raw-transcripts/
    2026-03-25 14-47-14.md
  normalized-transcripts/
    2026-03-25 14-47-14.md
  normalization-reports/
    2026-03-25 14-47-14.md
  speaker-summaries/
    2026-03-25 14-47-14.md
  audio-feature-summaries/
    2026-03-25 14-47-14.md
```

最初に開くべきファイルは `README.html` です。ここから timeline、transcript、normalization、speaker、feature の各 Markdown へリンクできます。

一部失敗した job では、追加で次が入ることがあります。

- `FAILURE_REPORT.md`
- `logs/worker.log`

## パイプライン概要

現在の MVP パイプラインは次の流れです。

1. 入力音声を probe して `source hash` を計算
2. 設定を正規化して `conversion signature` を計算
3. `faster-whisper` で文字起こし
4. Hugging Face 側の前提が揃っていれば `pyannote` で話者分離
5. pause、loudness、speaking rate、pitch、overlap、diarization heuristics を計算
6. 次を書き出し
   - `timeline.md`
   - raw transcript
   - normalized transcript
   - normalization report
   - speaker summary
   - audio feature summary
7. ZIP export を生成

## モデルと実行モード

- transcription backend: `faster-whisper`
- `standard` quality: `medium`
- `high` quality: `large-v3`
- diarization model: `pyannote/speaker-diarization-community-1`
- VAD / silence stack: `silero-vad` 系 metadata と `ffmpeg` の silence detection

計算モード:

- `CPU`
  - baseline path
  - 幅広い環境で使える
  - 遅め
- `GPU`
  - optional
  - Docker から使える NVIDIA GPU が必要
  - `high` 向き

`high` quality はおおむね 10 GB 以上の VRAM がある GPU を前提にしています。CPU でも `high` 実行はできますが、かなり遅くなります。

## Hugging Face の前提

完全な話者分離パイプラインを使うには、`Settings` に Hugging Face token を保存し、`pyannote/speaker-diarization-community-1` へのアクセス承認を済ませてください。

token や承認がない場合でも文字起こし自体はできますが、話者分離依存の summary は unavailable になります。

## クイックスタート

Windows:

```powershell
.\start.bat
```

macOS の source-based helper:

```bash
./start.command
```

起動後:

1. `Settings` を開く
2. 話者分離を使いたいなら Hugging Face token を保存する
3. `CPU` か `GPU` を選ぶ
4. `Standard` か `High` を選ぶ
5. 必要なら次を設定する
   - transcription initial prompt
   - transcript normalization glossary
6. ファイルまたはディレクトリから job を作る
7. duplicate modal で再利用か再処理かを選ぶ
8. 完了を待って ZIP をダウンロードする

## Duplicate 再利用に効くもの

duplicate 再利用はファイル hash だけでは決まりません。

保存しているのは:

- `source hash`
- `conversion signature`

`conversion signature` には、pipeline version、model family、compute mode、processing quality、diarization enabled state、initial prompt hash、normalization settings などが入ります。つまり、同じ元音声でも変換条件が変われば再処理対象にできます。

## アイテムごとに保存する metadata

現在のパイプラインでは、次のような metadata を保存します。

- duration
- size bytes
- extension / container
- audio codec
- channels
- sample rate
- bitrate
- model id
- pipeline version
- conversion signature
- processing wall time
- stage elapsed times
- pause / silence summary
- loudness summary
- speaking-rate summary
- pitch summary
- speaker confidence summary
- optional voice-feature summary

## CLI

通常利用の入口は GUI ですが、worker CLI も使えます。

主なコマンド:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

例:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m audio2timeline_worker settings status
python -m audio2timeline_worker jobs list
python -m audio2timeline_worker jobs show --job-id job-YYYYMMDD-HHMMSS-xxxx
python -m audio2timeline_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxx
```

## テスト

worker unit test:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

Docker build:

```powershell
docker compose build web worker
```

## ライセンス

このリポジトリは MIT License です。詳細は [LICENSE](LICENSE) を参照してください。

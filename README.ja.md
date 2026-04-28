# TimelineForAudio

手元にある音声ファイルを、ChatGPT などの LLM に渡しやすい IPA-first の markdown パッケージへ変換するローカルツールです。

[English README](README.md) | [サンプル成果物](docs/examples/sample-timeline.ja.md) | [仮ペルソナ](docs/PERSONA.ja.md) | [第三者ライセンス](THIRD_PARTY_NOTICES.md) | [モデルと実行環境メモ](MODEL_AND_RUNTIME_NOTES.md) | [セキュリティと安全性](docs/SECURITY_AND_SAFETY.md) | [公開前チェック](docs/PUBLIC_RELEASE_CHECKLIST.md) | [ライセンス](LICENSE)

## Public Release Status

現在の public release 系列は `TimelineForAudio v0.4.1 Tech Preview` です。

現時点の public contract:

- baseline support: Windows + Docker Desktop + CPU mode
- macOS: source-based experimental path
- GPU mode: optional, NVIDIA-only, Docker Compose の GPU worker overlay 経由
- 話者分離は optional で、`pyannote/speaker-diarization-community-1` の gated approval と Hugging Face token が必要
- これは local-first の desktop-style tool であり、hosted SaaS ではありません

## このアプリがやっていること

このアプリは、手元の音声ファイルを、確認しやすい 2 種類の成果物に変換します。

- `IPA.md`
- `Readable Text.md`

内部の主な流れは次のとおりです。

1. 入力音声を worker 向けの安定した形式に正規化します
2. 録音内容を cleanup 向けの source text に変換します
3. 話者分離が使える場合は、speaker-aware な turn にそろえます
4. turn ごとの IPA を canonical intermediate として作ります
5. IPA、言語ヒント、補助コンテキストから可読テキストを復元します
6. `IPA` 用 ZIP または `Readable Text` 用 ZIP にまとめます

turn ごとの音声相対タイムスタンプは保持します。ダウンロード ZIP に元の音声ファイル本体は入りません。

## どんな用途に向いているか

- 会議の振り返り
- 面談、通話、インタビューの整理
- ボイスメモや podcast archive のレビュー
- 会話ログの分析
- 手元の音声資産を LLM 向けメモへ変換する用途

## スクリーンショット

### 言語選択

![言語選択](docs/screenshots/language.png)

### 設定

![設定](docs/screenshots/settings.png)

### 新規ジョブ

![新規ジョブ](docs/screenshots/new-job.png)

### ジョブ一覧

![ジョブ一覧](docs/screenshots/jobs.png)

### ジョブ詳細

![ジョブ詳細](docs/screenshots/run-details.png)

## 基本的な流れ

1. 音声ファイルを選ぶ
2. 実行する
3. 完了まで待つ
   AI 処理を行うため、ある程度時間がかかります
4. `IPA ZIP` または `Readable Text ZIP` をダウンロードする
5. ZIP 内の `README.html` を開く
6. 必要なら、その ZIP を ChatGPT や Claude などの LLM に渡して活用する

たとえば、次のような使い方ができます。

- 会議内容を要約する
- 決定事項や宿題を抜き出す
- 自分の説明の癖を振り返る
- 会話パターンを分析する
- 音声の蓄積を検索しやすいメモにする

## ZIP に入るもの

ダウンロードされる ZIP は、用途ごとに compact に分かれています。

IPA ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `ipa/<収録日時>.md`

Readable Text ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `readable-text/<収録日時>.md`

例:

```text
TimelineForAudio-ipa.zip
  README.html
  CONVERSION_INFO.md
  ipa/
    2026-03-26 18-00-00.md

TimelineForAudio-readable-text.zip
  README.html
  CONVERSION_INFO.md
  readable-text/
    2026-03-26 18-00-00.md
```

`README.html` が export の入口です。生成物へのリンクと、変換内容の概要をそこから確認できます。

## 内部作業フォルダと ZIP の違い

Docker 内では、処理のためにもう少し大きな作業フォルダを持っています。

そこには、たとえば次のようなものが入ります。

- request / status / result / manifest の JSON
- worker ログ
- 正規化済み音声や probe 情報
- cleanup-source と turn-source の transcript JSON / markdown
- context builder artifact と transcript delta JSON
- IPA / readable-text の内部 artifact
- speaker alignment metadata
- 一時ファイル

これらはアプリ内部で使うものです。普段ユーザーが見るのは、ダウンロードした ZIP の中身だけで十分です。

## クイックスタート

Windows:

```powershell
.\start.bat
```

`v0.4.1` の public release では、これが primary supported path です。

Docker Compose は Web UI を `localhost` のみに公開し、`.env` の `TIMELINE_FOR_AUDIO_WEB_PORT` を使います。

Web UI の Tailwind CSS と TW Elements 資産は Docker 内でローカルビルドされます。実行時に Tailwind CDN へ依存しません。

macOS:

```bash
./start.command
```

こちらは `v0.4.1` では experimental な source-based path です。現在の public release line の baseline support には含めません。

起動後の流れ:

1. 言語を選ぶ
2. `Settings` を開く
3. 話者分離を使いたい場合は Hugging Face token を保存する
4. `CPU` か `GPU` を選ぶ
5. 新しいジョブを作る
6. 処理完了まで待つ
7. `IPA ZIP` または `Readable Text ZIP` をダウンロードする

worker に `transformers` を含めている理由は、IPA-first pipeline の `Readable Text` 復元をローカルで実行するためです。

起動スクリプトは、Google Chrome / Microsoft Edge / Brave / Chromium のいずれかで専用ウィンドウ風に開こうとします。使えない場合は通常のブラウザで開きます。

## 必要なもの

- primary supported path としての Windows
- experimental な source-based path としての macOS
- Docker Desktop
- 初回のコンテナ・モデル取得用のインターネット接続
- `pyannote` 話者分離を使う場合のみ Hugging Face token
- `pyannote` 話者分離を使う場合のみ gated approval
- GPU モードを使う場合は NVIDIA GPU と Docker GPU 対応

## 計算モード

public UI では、計算モードは 2 つだけです。

- `CPU`
  - baseline lane
  - もっとも広い環境で使えます
  - 速度は遅めです
- `GPU`
  - NVIDIA GPU が使える環境向けです
  - 対応環境ではより高速に動きます

モデル選択や復元の細かい差分は UI に出しません。現在の UI に `standard / high` の概念はありません。

この開発環境では `NVIDIA GeForce RTX 4070` で GPU 実行を確認しています。

## 対応する入力形式

主な対応形式:

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`

実際に読み込めるかどうかは、ランタイムイメージ内の `ffmpeg` に依存します。

## 言語対応

対応言語:

- `en`
- `ja`
- `zh-CN`
- `zh-TW`
- `ko`
- `es`
- `fr`
- `de`
- `pt`

初回起動時の既定は英語です。選択した言語は `.env` ではなくアプリ設定データに保存されます。

## CLI

通常利用の入口は GUI です。必要なら worker CLI も使えます。

初回 public release では GUI を primary path とします。CLI は advanced path であり、daemon と CLI を同時に回す運用は public support guarantee に含めません。

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
python -m timeline_for_audio_worker settings status
python -m timeline_for_audio_worker settings save --token hf_xxx --terms-confirmed
python -m timeline_for_audio_worker jobs create --file C:\path\to\clip.wav
python -m timeline_for_audio_worker jobs create --directory C:\path\to\folder
python -m timeline_for_audio_worker jobs list
python -m timeline_for_audio_worker jobs archive --job-id run-YYYYMMDD-HHMMSS-xxxx
```

`jobs archive` を使うと、GUI でダウンロードするのと同じ handoff 用 ZIP を出力できます。

## テスト

現在のテストは軽めです。

- Python worker の unit test
- ASP.NET Core UI の Playwright ベース smoke test
- 実データでの手動 smoke test

worker unit test:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

ブラウザ E2E:

```powershell
.\scripts\test-e2e.ps1
```

commit 前に lint を有効にする場合:

```powershell
git config core.hooksPath .githooks
```

## ライセンス

このリポジトリは MIT License です。詳細は [LICENSE](LICENSE) を参照してください。

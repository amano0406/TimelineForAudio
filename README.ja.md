# TimelineForAudio

TimelineForAudio は、音声ファイルを IPA-first の成果物へ変換するローカル CLI ツールです。

[English README](README.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [License](LICENSE)

## 現在の方針

Web UI は削除しました。対応する入口は Docker 内で実行する Python worker CLI です。

主な成果物はこれまでと同じです。

- `IPA.md`
- `Readable Text.md`
- IPA または Readable Text の ZIP

export ZIP には元の音声ファイルは含めません。

## できること

CLI では次を実行できます。

- ローカル設定の確認と保存
- 固定入力ディレクトリと固定出力先の管理
- 話者分離用の Hugging Face token 保存
- 設定済み入力ディレクトリの refresh
- 変化がない音声ファイルの自動スキップ
- 音声ファイルから単発 job 作成
- ローカル処理の実行
- job 一覧と詳細確認
- 完了 job から IPA ZIP または Readable Text ZIP を作成
- 生成済み turn artifact と正解 JSON の軽量評価

処理の流れは次です。

1. 音声を正規化する
2. 文字起こし用の中間テキストを作る
3. 可能なら話者 turn を合わせる
4. turn 単位の IPA を canonical intermediate として作る
5. 必要なら IPA と文脈から可読テキストを復元する
6. 成果物と ZIP を出力する

## 必要なもの

- Docker Desktop
- Docker engine が起動していること
- 初回モデル取得用のインターネット接続
- 話者分離を使う場合は Hugging Face token
- GPU mode を使う場合は NVIDIA GPU 環境

通常の CLI は Docker container 内でのみ実行します。ホストから直接
`python -m timeline_for_audio_worker ...` を実行する運用は許可していません。

ホストからは PowerShell の `tfa.ps1` を使って Docker 内 CLI を呼び出します。

## 最短実行

repo ルートで実行します。

```powershell
.\start.ps1
.\tfa.ps1 settings init
.\tfa.ps1 settings status
.\tfa.ps1 settings save --language ja --compute-mode cpu
.\tfa.ps1 refresh
```

IPA backend を実験的に切り替える場合:

```powershell
.\tfa.ps1 refresh --ipa-backend pyopenjtalk --ipa-only
```

既定の IPA backend は `sudachi` です。`pyopenjtalk` は実験用で、実行環境に optional package が入っている必要があります。

VAD の挙動を比較する場合:

```powershell
.\tfa.ps1 refresh --vad-profile loose --ipa-only
.\tfa.ps1 refresh --vad-profile strict --ipa-only
```

既定の VAD profile は現行互換の 500ms 無音区切りです。`loose` は 1000ms、`strict` は 250ms です。

話者分離を使う場合:

```powershell
.\tfa.ps1 settings save --token hf_xxx --terms-confirmed
```

IPA だけ作る場合:

```powershell
.\tfa.ps1 refresh --ipa-only
```

可読テキスト復元用の補足を渡す場合:

```powershell
.\tfa.ps1 refresh --language ja --supplemental-context-file ".\context.txt"
```

単発ファイルを直接指定したい場合:

```powershell
.\tfa.ps1 jobs create --file "C:\path\to\audio.mp3"
```

## 主なコマンド

- `settings status`
- `settings init`
- `settings save`
- `settings input-root list/add/remove/clear`
- `settings output-root list/set`
- `scan`
- `refresh`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`
- `evaluate`

例:

```powershell
.\tfa.ps1 jobs show --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
.\tfa.ps1 jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa
.\tfa.ps1 jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind readable-text
```

生成済み turn artifact の軽量評価:

```powershell
.\tfa.ps1 evaluate --prediction ".\outputs\job-...\media\media-0001\ipa\ipa_turns.json" --reference ".\references\case-001-ipa.json" --json
.\tfa.ps1 evaluate --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa --reference ".\references\case-001-ipa.json" --json
```

`evaluate` は text CER、IPA error rate、speaker label accuracy、speaker time mismatch proxy を出します。speaker time mismatch は回帰比較用の簡易指標で、厳密な DER ではありません。

正解fixtureの形式は [Evaluation Fixtures](docs/EVALUATION.md) にまとめています。

## Refresh

`refresh` は、設定済みの入力ディレクトリを読み直し、必要な音声だけを処理します。

- 入力ディレクトリは `settings input-root` で登録します。
- 出力先は `settings output-root set` で固定します。
- 以前と同じ音声ファイルで、生成条件も同じ場合は処理せずスキップします。
- 判定には `source hash + generation signature` を使います。
- 出力 ZIP 内の Markdown ファイル名には、録音日時またはファイル名から推定した日時を使います。

確認だけしたい場合:

```powershell
.\tfa.ps1 scan
```

処理対象をキューに入れるだけで、すぐ処理しない場合:

```powershell
.\tfa.ps1 refresh --queue-only
```

## ローカルデータ

永続設定は repo ルートに保存します。

- `settings.example.json`: Git 管理する設定例
- `settings.json`: ローカル設定。Git 管理しない

必要な場合は次で `settings.json` を作成します。

```powershell
.\tfa.ps1 settings init
```

token などの秘密情報と worker 状態の既定保存先:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix 系環境: `~/.timeline-for-audio`

必要なら環境変数で変更できます。

- `TIMELINE_FOR_AUDIO_APPDATA_ROOT`
- `TIMELINE_FOR_AUDIO_SETTINGS_PATH`
- `TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH`
- `TIMELINE_FOR_AUDIO_OUTPUTS_ROOT`
- `TIMELINE_FOR_AUDIO_UPLOADS_ROOT`

Hugging Face token は `settings.json` には書かず、app data root 配下の `secrets/huggingface.token` に保存します。

## Docker Worker

`start.ps1` が Windows の正面玄関です。worker container を起動するだけで、ブラウザは開きません。Docker image がない場合だけ Docker Compose が build します。

```powershell
.\start.ps1
```

Docker 内 CLI を実行する場合:

```powershell
.\tfa.ps1 settings status
```

`start.ps1` と `tfa.ps1` は `settings.json` の入力/出力ディレクトリから
`.docker/docker-compose.paths.yml` を自動生成します。

- 入力ディレクトリは Docker 内で read-only mount します。
- 出力ディレクトリは Docker 内で writable mount します。
- 存在しない入力ディレクトリは mount せず、scan 時に未検出または missing として扱います。
- `settings input-root` / `settings output-root` を変更した後は、次回の `tfa.ps1` 実行時に mount 定義を再生成します。
- 生成された `.docker/docker-compose.paths.yml` は Git 管理しません。

互換入口と裏口:

- `start.bat`, `tfa.bat`, `stop.bat` は PowerShell script を呼ぶだけの互換 wrapper です。
- `start.command` と `tfa.command` は WSL / Unix 用の裏口として残します。Windows の正面玄関ではありません。
- WSL / Unix の裏口で Windows 形式の設定パスから Docker mount を生成するには `pwsh` が必要です。`pwsh` がない場合、基本的な Docker CLI 呼び出しはできますが、ディレクトリ refresh は PowerShell 入口を使ってください。

GPU worker overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d worker
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
$env:TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI="1"
python -m unittest discover .\worker\tests
```

lint:

```powershell
.\scripts\lint.ps1
```

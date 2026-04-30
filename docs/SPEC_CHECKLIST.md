# TimelineForAudio Spec Checklist

## Product Definition

- [x] 音声ファイルから、元の時間軸を保ったまま発話情報を記録する
- [x] 話者は `SPEAKER_00` のような機械ラベルで扱う
- [x] 実名、本人性、性別、年齢、属性は推測しない
- [x] 意味解釈、要約、可読テキスト復元はこの製品の責務から外す
- [x] 主成果物を `speaker-acoustic-units-timeline.json` にする

## Source Audio Handling

- [x] 元音声ファイルは変更しない
- [x] 処理用の正規化音声を内部生成する
- [x] 発話候補区間を記録し、重い推論は短い区間単位で実行する
- [x] 切り出し結果を元音声上の時刻へ戻せるようにする
- [x] 元ファイル名、source hash、相対パス、録音日時候補を保持する

## Processing Flow

- [x] `settings.json` の入力ディレクトリを読む
- [x] `ffprobe` で長さ、形式、codec、sample rate、channel、sizeを取得する
- [x] SHA-256でファイル識別情報を持つ
- [x] 発話候補区間を作る
- [x] `pyannote/speaker-diarization-community-1` で話者分離する
- [x] ZIPA large ONNXバックエンドで音響単位を抽出する
- [x] 話者、時刻、音響単位を1つのタイムラインJSONに統合する

## Artifacts

- [x] `source/source-record.json`
- [x] `segments/speech-candidates.json`
- [x] `timeline/speaker-acoustic-units-timeline.json`
- [x] `timeline/speaker-acoustic-units-timeline.md`
- [x] `artifacts.json`
- [x] `RUN_PERFORMANCE.json`

## Reuse And Settings

- [x] 入力ディレクトリを `settings.json` で固定管理する
- [x] 出力ディレクトリを `settings.json` で固定管理する
- [x] `settings.example.json` はGit管理し、`settings.json` はGit管理しない
- [x] `items refresh` は設定済み入力ディレクトリを読む
- [x] `source hash + generation signature + source file identity` が同じ場合は再処理を避ける
- [x] ファイル名または相対パスが変わった場合は別ファイルとして扱う
- [x] `items refresh --max-items` で小さなバッチに分割できる

## Verification

- [x] Docker経由のCLIを通常入口にする
- [x] Windows PowerShellを正面玄関にする
- [x] WSL/Unix wrapperは開発者向け裏口として残す
- [x] CLIテストで設定、run、artifact、再利用判定を検証する

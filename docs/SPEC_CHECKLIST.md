# TimelineForAudio Spec Checklist

このファイルは、最新仕様を実装TODOとして管理するためのチェックリストです。

## Product Definition

- [x] 長時間音声から「いつ、誰が、どのような発音をしたか」を記録する
- [x] 通常の文字起こしではなく、IPAを主成果物として扱う
- [x] 録音全体の元タイムラインを保持する
- [x] 話者は `SPEAKER_00` のような機械ラベルで扱う
- [x] 実名、本人性、性別、年齢、属性は推測しない

## Source Audio Handling

- [x] 元音声ファイルは変更しない
- [x] 処理用のコピーを内部生成する
- [x] フルタイムラインの正規化音声を `audio/source-normalized.wav` に保存する
- [x] 発話候補だけをまとめた処理用音声を `audio/normalized.wav` に保存する
- [x] 切り出し結果を `audio/cut_map.json` に保存する
- [x] 切り出し後の時刻を元音声上の時刻へ戻せる

## Processing Flow

- [x] 音声ファイルを登録する
- [x] `ffprobe` で長さ、形式、codec、sample rate、channel、sizeを取得する
- [x] SHA-256でファイル識別情報を持つ
- [x] 音声全体を軽くスキャンして発話候補区間を作る
- [x] 発話候補区間の前後に余白を付けて切り出す
- [x] 重い音声AI処理は発話候補音声を中心に行う
- [x] 解析結果は元タイムラインへ戻す

## Timeline Events

- [x] 発話候補区間を記録する
- [x] 会話していない可能性が高い区間を `silence_or_noise_candidate` として記録する
- [x] 判定は候補情報として扱い、音の意味までは断定しない
- [x] タイムラインイベントを `analysis/timeline_events.json` に保存する
- [x] 人が読めるタイムラインイベントを `analysis/Timeline Events.md` に保存する

## Speaker Handling

- [x] 話者分離が使える場合は話者ラベルを付与する
- [x] 話者分離が使えない場合でも処理を継続する
- [x] 話者名や人物属性は出力しない
- [x] 話者数メタデータを保持する

## IPA Output

- [x] turn単位で時刻、話者、IPAを出力する
- [x] 元ファイル名を成果物に残す
- [x] language hintを成果物に残す
- [x] 信頼度が取得できる場合はIPA turnへ出力する
- [x] `ipa/IPA.md` を生成する
- [x] `ipa/ipa_turns.json` を生成する

## Reuse And Settings

- [x] 入力ディレクトリを `settings.json` で固定管理する
- [x] 出力ディレクトリを `settings.json` で固定管理する
- [x] `settings.example.json` はGit管理し、`settings.json` はGit管理しない
- [x] `refresh` は設定済み入力ディレクトリを読む
- [x] `source hash + generation signature + source file identity` が同じ場合は再処理を避ける
- [x] ファイル名または相対パスが変わった場合は別ファイルとして扱う

## Verification

- [x] Docker経由のCLIを通常入口にする
- [x] Windows PowerShellを正面玄関にする
- [x] WSL/Unix wrapperは開発者向け裏口として残す
- [x] CLIテストで設定、job、artifact、timeline eventを検証する

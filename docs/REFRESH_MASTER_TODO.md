# Refresh + Master TODO

このTODOは、固定入力ディレクトリを `refresh` し、音声ファイル単位のマスター成果物を更新する運用へ寄せるための管理表です。

## 要件

- [x] `settings.json` で複数の入力ディレクトリを固定管理する
- [x] `settings.json` でマスター出力ディレクトリを固定管理する
- [x] `settings.example.json` はGit管理し、`settings.json` はGit管理しない
- [x] Windows PowerShell / `.bat` / `.ps1` を正面玄関にする
- [x] `settings.json` から Docker Compose の入力/出力 mount を生成する
- [x] 入力ディレクトリは Docker 内で read-only mount する
- [x] 出力ディレクトリは Docker 内で writable mount する
- [x] `refresh` は設定済み入力ディレクトリをスキャンする
- [x] `refresh` は未処理または出力が変わる音声だけをキューに入れる
- [x] `source hash + generation signature + source file identity` が同じ場合はスキップする
- [x] ファイル名または相対パスが変わった場合は、同じ音声hashでも別ファイルとして扱う
- [x] 元ファイル名と相対パスを artifact / catalog に残す
- [x] マスター成果物はWindows側の出力ディレクトリに保存する
- [x] 重い音声ファイルのテストを避けるため、`C:\TimelineData\Audio` をサンプル入力にする
- [x] `C:\TimelineData\Audio` に軽量なサンプル音声を3件配置する
- [x] Docker CLIでサンプル3件の `refresh --ipa-only` を実行する
- [x] 2回目の `refresh --ipa-only` で3件がスキップされることを確認する
- [x] ファイル名だけ変えた同一音声が別ファイルとしてキューに入ることを実データで確認する

## 設計メモ

- `job` は実行ログであり、ユーザーが常に意識する主概念ではない。
- 主概念は、入力ディレクトリ内の音声ファイルと、そのファイルから生成されたマスター成果物。
- `source_file_identity` は `source_id:relative/path.ext` の形式で持つ。
- ファイル名やフォルダ名は、可読テキスト復元時の文脈になり得るため、同じ `source_hash` でも同一ファイル扱いにはしない。
- 入力/出力ディレクトリを変更した場合は Docker mount が変わるため、再起動が必要になる。

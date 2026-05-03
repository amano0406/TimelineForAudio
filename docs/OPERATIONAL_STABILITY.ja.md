# Operational Stability Checklist

この文書は、`TimelineForAudio` を他製品や管理 UI から安定して呼び出すための確認リストです。

## 現在できていること

- CLI の通常入口は `cli.ps1` に統一している。
- 通常利用では Python CLI の host 直接実行を止め、Docker worker 経由にしている。
- `settings.json` は Git 管理せず、テストでは隔離された一時 settings を使う。
- `items refresh` は、出力結果が変わらない対象を skip する。
- `items download` は、item 未指定時に利用可能な全 item を ZIP 化する。
- `items download` の ZIP には `README.md`、`convert_info.json`、`timeline.json` を含める。
- `--json` 付き CLI の実行時エラーは、可能な範囲で JSON error envelope を返す。
- `cli.ps1` wrapper も、`--json` 付きの worker 起動失敗を JSON error envelope に寄せる。
- 軽量 operational smoke test で、設定、ファイル一覧、queue-only refresh、run 一覧を確認している。
- `cli.ps1` 経由の download smoke test で、外部呼び出しに近い成功経路と JSON error 経路を確認している。
- 実モデル operational smoke test で、実音声、実モデル、download、2回目 refresh skip を確認できる。

## 残しておく確認

- release 前は、必要に応じて短い実音声で `test-operational.ps1 -UseRealModels` を実行する。
- Timeline 本体など外部 UI 側から呼ぶ場合は、`cli.ps1 ... --json` の stdout JSON と非 0 exit code の両方を確認する。
- Docker Desktop 停止、Hugging Face token 未設定、GPU 利用不可など、環境起因の失敗は外部 UI 側でも表示確認する。
- GPU 性能や並列処理は、実データ量が増えた段階で別途チューニングする。
- `settings.json` の壊れた JSON、存在しない input root、書き込み不可 output root は、運用前に代表ケースを確認する。

## 現時点の判断

Audio 製品内で直近の安定性に効く優先作業は、CLI error envelope と operational smoke coverage です。
これらは実装済みです。

残りは主に、外部 UI 側の呼び出しテスト、実モデル smoke の定期実行、GPU 性能チューニングです。
これらは重い処理や別製品の状態に依存するため、通常の軽量テストには含めません。

# CLI Output Contract

この文書は、TimelineForAudio CLI を別プロダクトや管理 UI から呼び出すための返却仕様です。

対象は通常利用する CLI です。`process-run` と `daemon` は Docker worker 用の内部コマンドなので、この契約の対象外です。

## 基本ルール

JSON として機械処理したい場合は、必ず `--json` を付けます。

```powershell
.\cli.ps1 items list --json
```

返却の基本:

| 条件 | stdout | exit code |
|---|---|---:|
| 成功 | JSON | `0` |
| 引数エラー | argparse のエラーテキスト | 非 0 |
| 実行時エラー | 例外メッセージまたは Docker のエラー | 非 0 |

注意:

- `--json` なしの表示は人間向けです。管理 UI からは使わないでください。
- JSON のフィールドは追加される可能性があります。呼び出し側は未知フィールドを無視してください。
- パスは、設定値由来なら Windows パス、Docker 内の処理結果なら container パスになることがあります。
- 破壊的操作は `--dry-run` がある場合、先に dry-run で確認できます。
- `settings validate-token` は token が無効でもコマンド自体は成功扱いで `exit code 0` を返します。判定は JSON 内の `valid` / `status` を見ます。
- それ以外の実行時エラーは、現時点では共通の JSON error envelope を保証しません。管理 UI 側は `exit code != 0` と stderr/stdout のテキストをエラーとして扱ってください。

共通エラー例:

| 条件 | 返却 |
|---|---|
| コマンド名や引数が不正 | 非 0。argparse の usage/error テキスト |
| 設定が壊れている | 非 0。JSON parse error または設定読み込みエラー |
| Docker が起動していない | 非 0。Docker / compose 側のエラーテキスト |
| path が存在しない | コマンドにより異なる。入力ファイル実処理では非 0、一覧系では空または `missing_sources` |
| Hugging Face API へ接続できない | `settings validate-token` は `valid=false`、`models list --include-remote` は model 行の `huggingface.remote_status=error` |

## `settings init`

用途:
`settings.json` がない場合に生成します。

```powershell
.\cli.ps1 settings init --json
```

成功時:

```json
{
  "created": true,
  "path": "/app/settings.json"
}
```

パターン:

| `created` | 意味 |
|---:|---|
| `true` | 新しく `settings.json` を作成した |
| `false` | 既に存在しているため変更しなかった |

補足:
既に存在する場合でもエラーではありません。既存設定を壊さず、そのまま `created=false` を返します。

## `settings status`

用途:
現在の設定が処理可能な状態か確認します。

```powershell
.\cli.ps1 settings status --json
```

成功時:

```json
{
  "setup": {
    "state": "ready",
    "blocking_reasons": []
  },
  "token": {
    "configured": true,
    "preview": "hf_a••••••••••••••••1234"
  },
  "compute": {
    "mode": "gpu"
  },
  "inputs": [
    {
      "id": "timeline-audio",
      "path": "C:\\TimelineData\\Audio\\"
    }
  ],
  "master": {
    "path": "C:\\TimelineData\\AudioMaster\\"
  }
}
```

主な判定:

| フィールド | 意味 |
|---|---|
| `setup.state` | `ready` / `needs_token` / `needs_input` / `needs_master` |
| `setup.blocking_reasons` | 処理開始を妨げる理由。なければ空配列 |
| `token.configured` | Hugging Face token が保存されているか |
| `token.preview` | token がある場合だけ返るマスク値 |
| `compute.mode` | `cpu` または `gpu` |
| `inputs` | 入力ディレクトリ一覧。各行は `id` と `path` |
| `master` | 単一のマスター保存先。未設定なら `null` |

パターン:

| パターン | 返却 |
|---|---|
| 処理可能 | `setup.state=ready`、`blocking_reasons=[]` |
| token なし | `setup.state=needs_token`、`token.configured=false` |
| 入力元なし | `setup.state=needs_input`、`inputs=[]` |
| マスター保存先なし | `setup.state=needs_master`、`master=null` |

## `settings validate-token`

用途:
Hugging Face token の形式と API 応答を確認します。

```powershell
.\cli.ps1 settings validate-token --json
.\cli.ps1 settings validate-token --token hf_xxx --json
```

成功時:

```json
{
  "valid": true,
  "status": "ok",
  "account_name": "account-name"
}
```

主な `status`:

| status | 意味 |
|---|---|
| `ok` | token を確認できた |
| `missing` | token が未設定 |
| `invalid_format` | `hf_` で始まらない、または短すぎる |
| `rejected` | Hugging Face が 401/403 を返した |
| `remote_error` | Hugging Face がその他 HTTP エラーを返した |
| `connection_error` | 通信できなかった |

パターン:

| パターン | exit code | 判定 |
|---|---:|---|
| 有効 token | `0` | `valid=true`, `status=ok` |
| 未設定 | `0` | `valid=false`, `status=missing` |
| 形式不正 | `0` | `valid=false`, `status=invalid_format` |
| Hugging Face に拒否された | `0` | `valid=false`, `status=rejected` |
| 通信失敗 | `0` | `valid=false`, `status=connection_error` |

## `settings save`

用途:
token と CPU/GPU を保存します。

```powershell
.\cli.ps1 settings save --token hf_xxx --compute-mode gpu --json
```

返却:
`settings status` と同じ snapshot です。

パターン:

| パターン | 返却 |
|---|---|
| `--token` 指定 | token を保存し、snapshot の `token.configured` / `token.preview` が更新される |
| `--token ""` 指定 | token を空にし、`token.configured=false` |
| `--compute-mode cpu` | `compute.mode=cpu` |
| `--compute-mode gpu` | `compute.mode=gpu` |

## `settings inputs`

用途:
複数の入力ディレクトリを管理します。

```powershell
.\cli.ps1 settings inputs list --json
.\cli.ps1 settings inputs add "C:\TimelineData\Audio\" --json
.\cli.ps1 settings inputs remove input-a7f3k9 --json
.\cli.ps1 settings inputs clear --json
```

成功時:
常に入力元の配列を返します。

```json
[
  {
    "id": "input-a7f3k9",
    "path": "C:\\TimelineData\\Audio\\"
  }
]
```

パターン:

| コマンド | 返却内容 |
|---|---|
| `list` | 現在の入力元一覧 |
| `add` | 追加後の入力元一覧。ID は `input-<6 hex>` 形式で自動生成 |
| `add` で同じ path | エラーにせず、既存一覧をそのまま返す |
| `remove` | 削除後の入力元一覧 |
| `remove` で存在しない ID | エラーにせず、既存一覧をそのまま返す |
| `clear` | 空配列 |

## `settings master`

用途:
生成物を保存する 1 箇所のマスター保存先を管理します。

```powershell
.\cli.ps1 settings master show --json
.\cli.ps1 settings master set "C:\TimelineData\AudioMaster\" --json
```

成功時:
マスター保存先の object を返します。

```json
{
  "path": "C:\\TimelineData\\AudioMaster\\"
}
```

パターン:

| コマンド | 返却内容 |
|---|---|
| `show` | 現在のマスター保存先。未設定なら `{}` |
| `set` | 保存後のマスター保存先 |

注意:
現時点では `set` 時にディレクトリの存在確認までは強制しません。実処理時には Docker の path mapping と保存先の実在性が必要です。

## `files list`

用途:
入力ディレクトリに現在存在する音声ファイルを一覧します。

```powershell
.\cli.ps1 files list --json
.\cli.ps1 files list --probe --json
```

成功時:

```json
[
  {
    "source_id": "timeline-audio",
    "source_display_name": "timeline-audio",
    "root_path": "C:\\TimelineData\\Audio\\",
    "relative_path": "meeting/sample.wav",
    "directory": "meeting",
    "file_name": "sample.wav",
    "display_path": "C:\\TimelineData\\Audio\\meeting\\sample.wav",
    "container_path": "/host/input/timeline-audio/meeting/sample.wav",
    "size_bytes": 123456,
    "modified_at": "2026-04-30T10:00:00+09:00",
    "duration_sec": 12.34,
    "status": "completed",
    "run_id": "run-20260430-100000-abcdef12",
    "media_id": "sample-12345678",
    "has_timeline": true,
    "has_audio": true,
    "turn_count": 8,
    "speaker_count": 2,
    "source_file_identity": "timeline-audio:meeting/sample.wav"
  }
]
```

主な `status`:

| status | 意味 |
|---|---|
| `unprocessed` | まだ生成物がない |
| `completed` | 現在のファイル内容と設定に対応する生成物がある |
| `queued` | refresh でキューに入っている |
| `processing` | worker が処理中 |
| `failed` | 実行中 run の manifest 上で失敗扱い |
| `settings_changed` | 同じ音声 hash の生成物はあるが、現在の generation signature と違う |
| `changed` | 過去生成物はあるが、現在のファイル hash と違う |

`--probe`:
未処理ファイルにも `duration_sec` を入れるため、ffprobe を実行します。件数が多い場合は遅くなる可能性があります。

パターン:

| パターン | 返却 |
|---|---|
| 対象ファイルなし | `[]` |
| 入力元ディレクトリが存在しない | 現在見つかったファイルだけ返る。低レベルな欠落確認は `files scan` の `missing_sources` を見る |
| `--probe` なし | 未処理ファイルの `duration_sec` は `null` になり得る |
| `--probe` あり | `duration_sec` を取得しようとする。取得失敗時は `null` |

## `files scan`

用途:
入力ディレクトリを素朴にスキャンします。catalog や生成物状態は見ません。

```powershell
.\cli.ps1 files scan --json
```

成功時:

```json
{
  "project_name": "TimelineForAudio",
  "total_audio_files": 3,
  "missing_sources": [],
  "audio_files": [
    {
      "source_name": "timeline-audio",
      "path": "/host/input/timeline-audio/sample.wav",
      "size_bytes": 123456
    }
  ]
}
```

パターン:

| パターン | 返却 |
|---|---|
| 対象ファイルなし | `total_audio_files=0`, `audio_files=[]` |
| 入力元が見つからない | `missing_sources` に欠落した source 情報 |
| `--output` 指定 | 同じ payload をファイルにも保存する |

## `items list`

用途:
TimelineForAudio が管理している生成済み item を一覧します。マスター内の `<item-id>` ディレクトリを正として読み取ります。

```powershell
.\cli.ps1 items list --json
```

成功時:

```json
[
  {
    "item_id": "sample-12345678",
    "media_id": "sample-12345678",
    "run_id": null,
    "run_dir": null,
    "source_id": "timeline-audio",
    "source_relative_path": "meeting/sample.wav",
    "source_file_identity": "timeline-audio:meeting/sample.wav",
    "source_file_name": "sample.wav",
    "source_hash": "sha256...",
    "conversion_signature": "signature...",
    "duration_sec": 12.34,
    "status": "available",
    "artifact_path": "/host/output/master/sample-12345678/timeline.json",
    "media_dir": "/host/output/master/sample-12345678",
    "turn_count": 8,
    "speaker_count": 2
  }
]
```

主な `status`:

| status | 意味 |
|---|---|
| `available` | item の timeline artifact が存在する |
| `missing_artifact` | catalog にはあるが、artifact ファイルが見つからない |

パターン:

| パターン | 返却 |
|---|---|
| 管理 item なし | `[]` |
| 元音声ファイルが消えている | catalog に残っていれば item は返る |
| 生成物 JSON が消えている | `status=missing_artifact` |

## `items refresh`

用途:
入力ディレクトリを読み直し、未処理または出力が変わる音声だけを処理します。

```powershell
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --max-items 3 --json
.\cli.ps1 items refresh --queue-only --json
.\cli.ps1 items refresh --source-id input-a7f3k9 --json
```

### 何も処理しない場合

```json
{
  "state": "skipped",
  "run_id": null,
  "run_dir": null,
  "artifact": "timeline",
  "queue_only": false,
  "total_discovered": 3,
  "missing_sources": [],
  "selected_count": 3,
  "queued_count": 0,
  "skipped_count": 3,
  "deferred_count": 0,
  "queued_limit": null,
  "skipped": [
    {
      "path": "/host/input/timeline-audio/sample.wav",
      "source_id": "timeline-audio",
      "source_relative_path": "sample.wav",
      "source_file_identity": "timeline-audio:sample.wav",
      "reason": "unchanged",
      "source_hash": "sha256...",
      "duplicate_of": "sample-12345678",
      "run_id": "run-..."
    }
  ],
  "deferred": [],
  "generation_signature": "signature..."
}
```

### キューだけ作った場合

```json
{
  "state": "pending",
  "run_id": "run-20260430-100000-abcdef12",
  "run_dir": "/tmp/timeline-for-audio/<master-key>/runs/run-20260430-100000-abcdef12",
  "artifact": "timeline",
  "queue_only": true,
  "queued_count": 3,
  "skipped_count": 0,
  "deferred_count": 0
}
```

### その場で処理した場合

```json
{
  "state": "completed",
  "run_id": "run-20260430-100000-abcdef12",
  "run_dir": "/tmp/timeline-for-audio/<master-key>/runs/run-20260430-100000-abcdef12",
  "artifact": "timeline",
  "queue_only": false,
  "queued_count": 3,
  "status": {
    "run_id": "run-20260430-100000-abcdef12",
    "state": "completed",
    "items_total": 3,
    "items_done": 3,
    "items_failed": 0,
    "items_skipped": 0,
    "progress_percent": 100.0
  },
  "result": {
    "run_id": "run-20260430-100000-abcdef12",
    "state": "completed",
    "items": []
  }
}
```

主な `state`:

| state | 意味 |
|---|---|
| `skipped` | 新規に処理する item がなかった |
| `pending` | run を作成した。`--queue-only` の場合はここで止まる |
| `running` | worker 処理中 |
| `completed` | 処理完了 |
| `failed` | 1 件以上失敗 |

`deferred`:
`--max-items` で今回キューに入れなかったファイルです。次回 `items refresh` で再判定されます。

主な配列:

| フィールド | 意味 |
|---|---|
| `skipped` | 既に同じ `source_hash`、`source_file_identity`、`generation_signature` の生成物があるため処理しなかったファイル |
| `deferred` | `--max-items` の上限で今回は後回しにしたファイル |
| `missing_sources` | 入力元ディレクトリとして見つからなかった source |

主なオプション:

| オプション | 返却への影響 |
|---|---|
| `--max-items N` | 最大 N 件だけ `queued` にし、残りは `deferred` |
| `--queue-only` | run を作るだけで処理しない。`state=pending` のまま返る |
| `--reprocess-duplicates` | 既存生成物があっても再処理対象にする |
| `--source-id` | 指定した入力元だけ refresh する。複数回指定可能 |

## `items remove`

用途:
指定した item の管理データと生成物を削除します。元音声ファイルは削除しません。

```powershell
.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json
.\cli.ps1 items remove --item-id item-a,item-b --json
```

成功時:

```json
{
  "dry_run": true,
  "requested_item_ids": ["item-a", "item-b"],
  "matched_count": 1,
  "missing_item_ids": ["item-b"],
  "catalog_rows_removed": 1,
  "media_dirs_removed": 0,
  "media_dirs": [
    "/host/output/master/sample-12345678"
  ],
  "unsafe_media_dirs": [],
  "removed_rows": [
    {
      "item_id": "item-a",
      "source_file_identity": "timeline-audio:sample.wav",
      "run_id": null,
      "media_id": "sample-12345678",
      "run_dir": null
    }
  ]
}
```

パターン:

| パターン | 返却 |
|---|---|
| 全件一致 | `matched_count` が指定数と同じ、`missing_item_ids` は空 |
| 一部不一致 | 見つかった分だけ削除し、見つからない ID は `missing_item_ids` に入る |
| `--dry-run` | `catalog_rows_removed` は削除予定 item 数、`media_dirs_removed` は `0`、物理削除しない |
| `unsafe_media_dirs` あり | 安全確認に失敗したため、その media dir は削除しない |
| `--item-id` が空 | 非 0。`At least one item id is required.` |

## `items download`

用途:
指定した item の生成物を ZIP にまとめます。

```powershell
.\cli.ps1 items download --item-id item-a,item-b --json
.\cli.ps1 items download --item-id item-a,item-b --output "C:\Temp\items.zip" --json
.\cli.ps1 items download --all --json
.\cli.ps1 items download --all --output "C:\Temp\all-items.zip" --json
```

成功時:

```json
{
  "archive_path": "/workspace/output/timelineforaudio-items-20260430-100000.zip",
  "item_ids": ["item-a", "item-b"],
  "all": false
}
```

ZIP 内容:

```text
README.md
<item-id>/conversion-info.json
<item-id>/timeline.json
```

エラーパターン:

| 条件 | 結果 |
|---|---|
| item が存在しない | 非 0。`Item not found: ...` |
| item はあるが artifact がない | 非 0。`No completed item artifacts are available to download.` |
| `--item-id` が空 | 非 0。`At least one item id is required.` |
| `--all` | `status=available` の全 item を ZIP に含める |
| `--all` と `--item-id` を同時指定 | 非 0。`Use either --all or --item-id, not both.` |
| `--all` で利用可能 item がない | 非 0。`At least one available item id is required.` |
| `--output` に `.zip` を指定 | 指定 path に ZIP を作る |
| `--output` に拡張子なしを指定 | その path に `.zip` を付けて作る |
| `--output` なし | Docker 通常利用ではプロジェクトの `output` ディレクトリに `timelineforaudio-items-<timestamp>.zip` を作る |

## `runs list`

用途:
実行単位を一覧します。これは診断・開発者向けです。run 情報は一時的な実行状態で、マスター成果物ではありません。

```powershell
.\cli.ps1 runs list --json
```

成功時:

```json
[
  {
    "run_id": "run-20260430-100000-abcdef12",
    "run_dir": "/tmp/timeline-for-audio/<master-key>/runs/run-20260430-100000-abcdef12",
    "state": "completed",
    "current_stage": "completed",
    "items_total": 3,
    "items_done": 3,
    "items_skipped": 0,
    "items_failed": 0,
    "updated_at": "2026-04-30T10:05:00+00:00",
    "created_at": "2026-04-30T10:00:00+00:00",
    "total_size_bytes": 123456,
    "total_duration_sec": 123.4
  }
]
```

パターン:

| パターン | 返却 |
|---|---|
| run なし | `[]` |
| 実行待ち | `state=pending` |
| 実行中 | `state=running` |
| 完了 | `state=completed` |
| 失敗 | `state=failed` |

## `runs show`

用途:
指定 run の `request.json`、`status.json`、`result.json` をまとめて返します。

```powershell
.\cli.ps1 runs show --run-id run-20260430-100000-abcdef12 --json
```

成功時:

```json
{
  "run_id": "run-20260430-100000-abcdef12",
  "run_dir": "/tmp/timeline-for-audio/<master-key>/runs/run-20260430-100000-abcdef12",
  "request": {},
  "status": {},
  "result": {},
  "performance": {}
}
```

`performance` は `RUN_PERFORMANCE.json` がある場合だけ含まれます。

パターン:

| パターン | 返却 |
|---|---|
| run が存在する | `request`、`status`、`result` を返す |
| `RUN_PERFORMANCE.json` あり | `performance` も返す |
| run が存在しない | 非 0。`Run not found: ...` |

## `models list`

用途:
使用するモデルやモデル相当の処理部品を一覧します。ライセンス確認や利用条件確認に使います。

```powershell
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

成功時:

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-30T10:00:00+00:00",
  "pipeline": {
    "name": "TimelineForAudio",
    "pipeline_version": "v...",
    "compute_mode": "gpu",
    "generation_signature": "signature..."
  },
  "models": [
    {
      "role": "speaker_diarization",
      "display_name": "Speaker diarization",
      "source": "huggingface",
      "model_id": "pyannote/speaker-diarization-community-1",
      "backend": "pyannote.audio",
      "required": true,
      "configured": true,
      "requires_huggingface_token": true,
      "requires_access_approval": true,
      "url": "https://huggingface.co/pyannote/speaker-diarization-community-1"
    }
  ]
}
```

現在返る主な `role`:

| role | 意味 |
|---|---|
| `speaker_diarization` | 話者分離。現在は `pyannote/speaker-diarization-community-1` |
| `acoustic_unit_extraction` | phone-like acoustic unit 抽出。現在は ZIPA 系 |
| `speech_candidate_detection` | 発話候補検出。Hugging Face model ではなくローカル処理 |

`--include-remote` を付けると、Hugging Face 由来の model 行に `huggingface` が追加されます。

```json
{
  "huggingface": {
    "remote_status": "ok",
    "id": "model-id",
    "sha": "revision",
    "last_modified": "2026-04-30T00:00:00.000Z",
    "private": false,
    "gated": "auto",
    "disabled": false,
    "pipeline_tag": "audio-classification",
    "library_name": "transformers",
    "license": "apache-2.0",
    "license_source": "cardData.license",
    "tags": [],
    "downloads": 123,
    "likes": 45,
    "model_card_url": "https://huggingface.co/model-id"
  }
}
```

Remote 取得失敗時:

```json
{
  "huggingface": {
    "remote_status": "error",
    "http_status": 403,
    "error": "Hugging Face returned HTTP 403."
  }
}
```

パターン:

| パターン | 返却 |
|---|---|
| `--include-remote` なし | remote metadata は付かない |
| `--include-remote` あり、取得成功 | Hugging Face model 行に `huggingface.remote_status=ok` |
| `--include-remote` あり、取得失敗 | Hugging Face model 行に `huggingface.remote_status=error` |
| `--output` 指定 | 同じ payload をファイルにも保存する |


## 管理 UI 側の推奨判定

管理 UI や別プロダクトから使う場合は、次の順で扱います。

1. すべて `--json` 付きで呼ぶ。
2. `exit code != 0` はコマンド失敗として扱い、stdout/stderr のテキストをそのまま詳細に出す。
3. `settings validate-token` だけは `exit code 0` でも `valid=false` なら設定未完了として扱う。
4. 一覧系コマンドは空配列を正常な空状態として扱う。
5. `items remove` は `missing_item_ids` があってもコマンド成功として扱い、削除できた件数と見つからなかった ID を分けて表示する。
6. `items refresh` は `state` と `queued_count` を主判定にし、`skipped` / `deferred` は詳細表示に回す。

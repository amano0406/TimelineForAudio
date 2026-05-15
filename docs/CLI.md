# CLI Contract

[Back to README](../README.md)

This document defines the stable CLI surface for callers such as management UIs and downstream Timeline products.

Use Windows PowerShell as the normal entrypoint:

```powershell
.\cli.ps1 <command> --json
```

`cli.bat` is only a compatibility wrapper for launchers that cannot invoke PowerShell scripts directly.

## JSON Rules

Machine callers should use `--json`.

| Condition | stdout | Exit code |
|---|---|---:|
| Success | JSON payload | `0` |
| Argument error | argparse-style text | non-zero |
| Runtime error with `--json` | JSON error envelope when possible | non-zero |
| Runtime error without `--json` | human-readable text | non-zero |

Error envelope:

```json
{
  "ok": false,
  "error": {
    "type": "ValueError",
    "message": "At least one available item id is required."
  }
}
```

Callers should treat non-zero exit code as failure. If stdout contains a JSON error envelope, show `error.message` to the user.

Unknown JSON fields may be added later. Callers should ignore fields they do not use.

## Settings Commands

```powershell
.\cli.ps1 settings init --json
.\cli.ps1 settings status --json
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json
.\cli.ps1 settings inputs list --json
.\cli.ps1 settings inputs add "C:\TimelineData\input-audio\" --json
.\cli.ps1 settings inputs remove "C:\TimelineData\input-audio\" --json
.\cli.ps1 settings inputs clear --json
.\cli.ps1 settings master show --json
.\cli.ps1 settings master set "C:\TimelineData\audio" --json
```

`settings.json` stores input roots, output root, Hugging Face token, compute mode, and local runtime settings.

The canonical token key is `huggingFaceToken`. Older local files with `huggingfaceToken` are read and saved back using the canonical key.

## File Commands

```powershell
.\cli.ps1 files list --json
.\cli.ps1 files list --page 1 --page-size 50 --json
.\cli.ps1 files list --probe --json
.\cli.ps1 files scan --json
```

`files list` reads configured input directories and returns current source audio files with known item status.

Without paging flags, list commands return the complete result set. Use `--page` and `--page-size` only when a caller wants a smaller response.

Common file statuses:

| Status | Meaning |
|---|---|
| `unprocessed` | no matching generated item exists |
| `completed` | matching generated item exists |
| `queued` | queued by refresh |
| `processing` | worker is processing it |
| `failed` | current run marked it as failed |
| `settings_changed` | source hash matches but generation signature differs |
| `changed` | previous item exists but source hash differs |

## Item Commands

```powershell
.\cli.ps1 items list --json
.\cli.ps1 items list --page 1 --page-size 50 --json
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --max-items 3 --json
.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json
.\cli.ps1 items remove --item-id item-a,item-b --json
.\cli.ps1 items download --json
.\cli.ps1 items download --item-id item-a,item-b --json
.\cli.ps1 items download --output "C:\Temp\items.zip" --json
```

`items list` reads master artifacts and returns generated item records.

`items refresh` processes only files whose output would change.

`items download` creates a ZIP. If `--item-id` is omitted, every available item is included.

When `--output` is a Windows host path, `cli.ps1` writes the ZIP to that exact host path and returns the same path in `archive_path`.

`items remove` deletes generated item artifacts from the master output. It does not delete source audio files.

## Diagnostic Commands

```powershell
.\cli.ps1 runs list --json
.\cli.ps1 runs show --run-id <run-id> --json
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

`runs` commands are diagnostic. Run directories are internal runtime state, not user-facing artifacts.

`models list` is for dependency, license, and model-access review.

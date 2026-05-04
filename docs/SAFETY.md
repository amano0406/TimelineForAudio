# Safety

[Back to README](../README.md)

TimelineForAudio is a local CLI tool. It is not a hosted service and does not sandbox the host machine.

The main safety risk is reading or deleting files outside the intended local directories.

## Current Boundaries

- source audio files are read from configured input directories
- source audio files are not deleted by item cleanup
- generated item cleanup removes selected master item directories
- run logs, locks, and scratch files are internal runtime data
- output ZIPs are written under the project `output` directory unless `--output` is specified
- Hugging Face tokens are stored in local-only `settings.json`, which is not tracked by Git

## Delete Operations

`items remove` deletes generated artifacts only.

Use `--dry-run` first when selecting item IDs from another UI:

```powershell
.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json
```

`uninstall.ps1` is broader and can remove Docker runtime data if requested. Use it only when cleaning the local installation.

## Non-Goals

This product does not claim:

- OS-level sandboxing
- hardened secret management
- protection from intentional misuse of dangerous paths
- hosted multi-tenant isolation

## Ongoing Checks

- keep `settings.json` ignored by Git
- keep sample paths generic
- review delete path validation when cleanup logic changes
- keep operational smoke coverage for settings, refresh, item list, item removal, and download ZIP creation

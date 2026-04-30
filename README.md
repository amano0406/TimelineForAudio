# TimelineForAudio

TimelineForAudio is a local Docker-first CLI tool for turning configured audio directories into speaker-attributed acoustic-unit timelines.

The product does not reconstruct readable text, infer real speaker names, or summarize meaning. It prepares audio in a structured form that downstream tools can use.

## Current Pipeline

1. Read audio files from configured input directories.
2. Normalize each audio file for processing without modifying the original file.
3. Detect speech candidate ranges and keep original audio-relative timestamps.
4. Run required speaker diarization with `pyannote/speaker-diarization-community-1`.
5. Extract acoustic units with the current ZIPA large ONNX backend in small speech-candidate chunks.
6. Write the primary JSON artifact.

Long recordings are not sent to ZIPA as one large inference request. Speech candidates are chunked internally and merged back to the original timeline.

Primary artifact:

```text
media/<media-id>/timeline/speaker-acoustic-units-timeline.json
```

Support artifacts:

```text
media/<media-id>/source/source-record.json
media/<media-id>/segments/speech-candidates.json
media/<media-id>/artifacts.json
RUN_PERFORMANCE.json
```

## Settings

Persistent settings are stored in:

```text
C:\apps\TimelineForAudio\settings.json
```

`settings.example.json` is tracked by Git. `settings.json` is local-only and is not tracked.

Default shape:

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    {
      "id": "timeline-audio",
      "path": "C:\\TimelineData\\Audio\\"
    }
  ],
  "outputRoot": {
    "path": "C:\\TimelineData\\AudioMaster\\"
  },
  "audioExtensions": [".mp3", ".wav", ".m4a", ".aac", ".flac"],
  "huggingfaceToken": "",
  "computeMode": "cpu"
}
```

`items refresh` queues all changed files by default. Use `items refresh --max-items <N>` when you want a smaller test or retry batch.

## Windows Entry Points

Use PowerShell from the project directory.

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu
.\cli.ps1 items refresh
.\cli.ps1 files list --json
.\cli.ps1 items list --json
.\cli.ps1 items remove --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --dry-run --json
.\cli.ps1 items download --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --json
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
.\stop.ps1
```

Use `.\cli.ps1 items refresh --reprocess-duplicates` only when you intentionally want to recompute unchanged files.

`items remove` does not delete the source audio file. It removes the managed item rows and generated `run-*/media/<media-id>` directories for the selected `item_id` values, so the next `items refresh` treats those source files as unprocessed. Use `--dry-run` before deleting when a management UI needs a confirmation step.

For JSON output details used by management UIs or other products, see [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md).

List model inventory for license and usage-condition review:

```powershell
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

`--include-remote` asks the Hugging Face API for license / gated / tags metadata. Treat the upstream model page as the final source of truth.

## CLI Structure

The CLI separates source files, managed items, execution runs, and fixed settings.

### Command Groups

| Command group | Role |
|---|---|
| `files` | Inspect source files that currently exist in configured input directories |
| `items` | Manage TimelineForAudio analysis targets and their generated data |
| `runs` | Inspect execution runs. Mainly diagnostic and developer-facing |
| `settings` | Manage fixed configuration. Inputs are multiple; the master location is single |

Main commands:

```powershell
.\cli.ps1 files list
.\cli.ps1 items list
.\cli.ps1 items refresh
.\cli.ps1 items remove --item-id <ITEM_ID_1>,<ITEM_ID_2>
.\cli.ps1 items download --item-id <ITEM_ID_1>,<ITEM_ID_2>
.\cli.ps1 runs list
.\cli.ps1 runs show --run-id <RUN_ID>
```

`settings` should clearly separate multiple input locations from the single master storage location.

```powershell
.\cli.ps1 settings inputs add "C:\TimelineData\Audio\"
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs remove input-a7f3k9
.\cli.ps1 settings master set "C:\TimelineData\AudioMaster\"
.\cli.ps1 settings master show
```

### Separating `files` and `items`

`files` is for source audio files that currently exist in the configured input directories. It should not manage files that existed in the past but have since been removed, and it should not remove generated data.

`items` is for analysis targets managed by TimelineForAudio. A generated item can remain managed even when the original source file no longer exists in the input directory. For that reason, generated-data removal and download belong under `items`, not `files`.

`items remove` does not delete the original source audio. It removes only the managed item data and generated artifacts for the selected `item_id` values. Multiple `item_id` values can be passed as a comma-separated list. If the source file still exists in an input directory, the next `items refresh` can recreate the item.

`items download` retrieves generated data for the selected `item_id` values. When multiple IDs are provided, they are downloaded together. There is no separate `outputs` command group; generated data is treated as part of the item.

### Removed Old Commands

| Old command | Current handling | Intent |
|---|---|---|
| `settings input-root` | `settings inputs` | Inputs are multiple, so use a plural command group |
| `settings output-root` | `settings master` | The generated-data master location is single |
| `scan` | `files scan` | Group source-file inspection under `files` |
| `files delete-generated` | `items remove --item-id <ITEM_ID>` | Remove generated data through managed items, not current source files |
| `refresh` | `items refresh` | Refresh updates managed items, so it belongs under `items` |
| `runs archive` | Remove | Run-scoped download should not be provided |
| `process-run` | Internal command | Hide from normal user workflows |
| `daemon` | Internal command | Hide from normal user workflows |

### Input Directory Management

Input directories should not require users to invent stable identifiers. The CLI keeps this to add, list, and remove.

```powershell
.\cli.ps1 settings inputs add "C:\TimelineData\Audio\"
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs remove input-a7f3k9
```

Direction:

- Do not ask for an ID during `add`
- Generate a short random ID such as `input-a7f3k9`
- Treat the ID as an operation handle for removal or targeted refresh, not as a user concept
- Avoid `display-name` in the main path
- Do not use `enable` / `disable`. Unused input directories should be removed
- To change a path, remove the old input directory and add the new path

`source_file_identity` may also move away from the input ID and toward an identity based on the input directory path plus the relative file path. This would let a re-added input directory keep the same file identity when the directory path and relative file path are unchanged.

Example:

```text
root-b4c91a:20220401020001.m4a
```

This affects reuse behavior, so it should be handled as a separate breaking change from the command naming cleanup.

## Required External Setup

- Windows with Docker Desktop installed and running.
- Hugging Face token.
- Access approval for `pyannote/speaker-diarization-community-1`.
- Input directories mounted through the Docker startup scripts.

## Output Semantics

Speaker labels are mechanical labels such as `SPEAKER_00` and `SPEAKER_01`.

The timeline preserves:

- original source filename
- source hash
- audio-relative timestamps
- best-effort recorded datetime when available
- timezone metadata when known
- speaker label
- acoustic units

TimelineForAudio intentionally does not use language hints, supplemental text, or downstream LLM text restoration.

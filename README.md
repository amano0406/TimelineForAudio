# TimelineForAudio

TimelineForAudio is a local Docker-first CLI product that turns audio files into reusable speaker/time/acoustic-unit timeline data.

## What This Product Does

TimelineForAudio reads configured audio directories, detects changed audio files, and creates structured timeline artifacts for downstream Timeline products or LLM workflows.

It preserves source-audio-relative time, assigns mechanical speaker labels such as `SPEAKER_00`, and stores acoustic units from the current phone-recognition backend.

It does not create readable prose, summaries, real speaker names, or identity guesses.

## Input

The user provides fixed input directories in:

```text
C:\apps\TimelineForAudio\settings.json
```

Each input directory is scanned for supported audio files. Source audio files are read only and are not modified.

The Git-managed template is:

```text
C:\apps\TimelineForAudio\settings.example.json
```

## Output

The primary output is:

```text
<outputRoot>/<item-id>/timeline.json
```

Each generated item contains:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

`timeline.json` contains source metadata, speaker labels, time ranges, and acoustic-unit tokens.

`convert_info.json` contains source fingerprint, model/runtime metadata, processing-flow metadata, counts, and artifact names.

Download ZIPs contain:

```text
README.md
items/
  <item-id>/
    convert_info.json
    timeline.json
```

Source audio files are not included in master output or download ZIPs.

## Quick Start

Run from Windows PowerShell:

```powershell
cd C:\apps\TimelineForAudio
.\start.ps1
.\cli.ps1 settings init --json
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json
.\cli.ps1 items refresh --json
.\cli.ps1 items list --json
.\cli.ps1 items download --json
```

Use CPU mode when GPU is unavailable:

```powershell
.\cli.ps1 settings save --compute-mode cpu --json
```

## Sample

Committed sample audio is not included yet.

For a local smoke test, put a short audio file in one configured input directory, then run:

```powershell
.\cli.ps1 files list --json
.\cli.ps1 items refresh --max-items 1 --json
.\cli.ps1 items download --json
```

## Common Commands

| Purpose | Command |
|---|---|
| Start Docker worker | `.\start.ps1` |
| Stop Docker worker | `.\stop.ps1` |
| Create settings if missing | `.\cli.ps1 settings init --json` |
| Save token / compute mode | `.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json` |
| Add input directory | `.\cli.ps1 settings inputs add "C:\TimelineData\input-audio\" --json` |
| Show master output path | `.\cli.ps1 settings master show --json` |
| Set master output path | `.\cli.ps1 settings master set "C:\TimelineData\audio" --json` |
| List source audio | `.\cli.ps1 files list --json` |
| Process changed files | `.\cli.ps1 items refresh --json` |
| Process a small batch | `.\cli.ps1 items refresh --max-items 3 --json` |
| List generated items | `.\cli.ps1 items list --json` |
| Remove generated items | `.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json` |
| Create download ZIP | `.\cli.ps1 items download --json` |
| Show model inventory | `.\cli.ps1 models list --json` |
| Uninstall local containers | `.\uninstall.ps1` |

## Detailed Docs

| Document | When to read it |
|---|---|
| [docs/CLI.md](docs/CLI.md) | Calling the CLI from another product or management UI |
| [docs/OUTPUTS.md](docs/OUTPUTS.md) | Reading master artifacts and download ZIPs |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Understanding the processing pipeline |
| [docs/RUNTIME.md](docs/RUNTIME.md) | Docker, storage, model, GPU, and token requirements |
| [docs/TESTING.md](docs/TESTING.md) | Running lightweight and operational checks |
| [docs/SAFETY.md](docs/SAFETY.md) | Understanding deletion and local-file boundaries |
| [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) | Reviewing dependency and model notices |

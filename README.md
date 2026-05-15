# TimelineForAudio

TimelineForAudio is a local Docker-first CLI product that converts local audio files into speaker/time/transcript timeline data.

The product is currently CLI-first. A minimal C#/.NET health API is available only for runtime readiness checks and future API migration preparation.

## Role

TimelineForAudio reads configured audio directories, detects changed audio files, and creates structured timeline artifacts for downstream Timeline products or LLM workflows.

It preserves source-audio-relative time, assigns mechanical speaker labels such as `SPEAKER_00`, and stores Whisper transcript text without rewriting it.

It does not create summaries, real speaker names, or identity guesses.

## Settings

Local settings live at:

```text
C:\apps\TimelineForAudio\settings.json
```

Current shape:

```json
{
  "schemaVersion": 1,
  "runtime": {
    "instanceName": "ff4e43e190",
    "apiPort": 19100
  },
  "inputRoots": [
    "C:\\apps\\Timeline\\data\\input\\audio"
  ],
  "outputRoot": "C:\\apps\\Timeline\\data\\to_text\\audio",
  "huggingFaceToken": "***REDACTED***",
  "computeMode": "gpu"
}
```

`huggingFaceToken` is the canonical token key. Older local files that still contain `huggingfaceToken` are read for compatibility and saved back using `huggingFaceToken`.

`runtime.instanceName` identifies this local Docker runtime. `runtime.apiPort` is used by the local health API.

## Runtime

Run from Windows PowerShell:

```powershell
cd C:\apps\TimelineForAudio
.\start.ps1
```

`start.ps1` starts:

- Docker worker
- local health API

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:19100/health
```

The response body is a JSON boolean:

```json
true
```

No other API routes are part of the current contract. Product operations still go through `cli.ps1`.

## Output

Generated item output is written under `outputRoot`:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

`timeline.json` contains source metadata, speaker labels, time ranges, and transcript text.

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

For concrete JSON structures and field meanings, see [docs/OUTPUTS.md](docs/OUTPUTS.md).

## Common Commands

| Purpose | Command |
|---|---|
| Start Docker worker and health API | `.\start.ps1` |
| Stop Docker worker and health API | `.\stop.ps1` |
| Check local health API | `Invoke-RestMethod http://127.0.0.1:19100/health` |
| Create settings if missing | `.\cli.ps1 settings init --json` |
| Show settings status | `.\cli.ps1 settings status --json` |
| Save token / compute mode | `.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json` |
| Add input directory | `.\cli.ps1 settings inputs add "C:\apps\Timeline\data\input\audio" --json` |
| Show master output path | `.\cli.ps1 settings master show --json` |
| Set master output path | `.\cli.ps1 settings master set "C:\apps\Timeline\data\to_text\audio" --json` |
| List source audio | `.\cli.ps1 files list --json` |
| Process changed files | `.\cli.ps1 items refresh --json` |
| Process a small batch | `.\cli.ps1 items refresh --max-items 3 --json` |
| List generated items | `.\cli.ps1 items list --json` |
| Remove generated items dry-run | `.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json` |
| Remove generated items | `.\cli.ps1 items remove --item-id item-a,item-b --json` |
| Create download ZIP | `.\cli.ps1 items download --json` |
| Show model inventory | `.\cli.ps1 models list --json` |
| Uninstall local containers | `.\uninstall.ps1` |

## Validation

Lightweight validation:

```powershell
.\scripts\lint.ps1
```

Operational validation with isolated generated data:

```powershell
.\scripts\lint.ps1 -IncludeOperationalSmoke
```

Real-model operational validation:

```powershell
.\scripts\test-operational.ps1 -UseRealModels
```

The operational tests use isolated settings, isolated Docker project names, and temporary input/output roots.

## Detailed Docs

| Document | When to read it |
|---|---|
| [docs/CLI.md](docs/CLI.md) | Calling the CLI from another product or management UI |
| [docs/OUTPUTS.md](docs/OUTPUTS.md) | Reading master artifacts and download ZIPs |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Understanding the processing pipeline |
| [docs/RUNTIME.md](docs/RUNTIME.md) | Docker, storage, model, GPU, token, and local-file boundaries |
| [docs/TESTING.md](docs/TESTING.md) | Running lightweight and operational checks |
| [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) | Reviewing dependency and model notices |

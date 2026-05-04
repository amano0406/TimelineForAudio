# TimelineForAudio

`TimelineForAudio` is a local Docker-first CLI product that reads configured audio directories and keeps speaker/time/phone-token artifacts up to date.

Japanese README: [README.ja.md](README.ja.md)

## README Role

This README is the entry point for first-time setup and daily operation.

- Understand what this product does.
- Start, configure, refresh, and export from Windows PowerShell.
- See which files are public artifacts.
- Jump to `docs/` for detailed contracts and operational notes.

The full CLI output contract, pipeline details, stability checklist, and release procedure live under `docs/`.

## Role In The Timeline Product Family

`TimelineForAudio` is not the product that creates the final human-readable text. It is a sub-product that converts audio into structured data that downstream Timeline products and LLM workflows can reuse.

The central asset is the original audio timeline. For long recordings, the product records when speech happened, which machine speaker label was active, and which phone tokens were observed.

This product does not interpret meaning. It does not infer real speaker names. Readable-text reconstruction, summarization, and conversation interpretation belong to downstream products or LLM workflows that consume `timeline.json`.

For that reason, the public surface stays intentionally small: configured input directories, `settings.json`, master artifacts, download ZIPs, and CLI JSON output. Run state, logs, caches, and temporary files are internal implementation details.

## Product Scope

TimelineForAudio does:

- read audio files from configured input directories
- skip unchanged files by source hash, source file identity, and generation signature
- preserve the original audio-relative timeline
- run required speaker diarization with `pyannote/speaker-diarization-community-1`
- extract phone tokens with the ZIPA large ONNX backend
- write `timeline.json` and `convert_info.json` per analyzed item
- create a small handoff ZIP on demand

TimelineForAudio does not:

- provide a Web UI
- reconstruct readable text
- summarize or interpret meaning
- infer real speaker names, identity, age, gender, or attributes
- modify source audio files
- expose run directories or scratch files as user-facing artifacts

## Requirements

- Windows PowerShell is the primary entrypoint.
- Docker Desktop is required.
- A Hugging Face token is required.
- Speaker diarization requires access approval for `pyannote/speaker-diarization-community-1`.
- GPU mode is optional and only used when NVIDIA GPU support is available from Docker.

## Quick Start

Run commands from the repository root:

```powershell
cd C:\apps\TimelineForAudio
```

Start the Docker worker:

```powershell
.\start.ps1
```

Create local settings if missing:

```powershell
.\cli.ps1 settings init --json
```

Save token and compute mode:

```powershell
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu --json
```

Use CPU mode when needed:

```powershell
.\cli.ps1 settings save --compute-mode cpu --json
```

Check configured inputs and master output:

```powershell
.\cli.ps1 settings inputs list --json
.\cli.ps1 settings master show --json
```

List audio files and process changes:

```powershell
.\cli.ps1 files list --json
.\cli.ps1 items refresh --json
```

List generated items and create a ZIP:

```powershell
.\cli.ps1 items list --json
.\cli.ps1 items download --json
```

## Settings

Normal operation uses:

```text
C:\apps\TimelineForAudio\settings.json
```

`settings.json` is local-only and not committed. The Git-managed template is `settings.example.json`.

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    "C:\\TimelineData\\input-audio\\"
  ],
  "outputRoot": "C:\\TimelineData\\audio",
  "huggingfaceToken": "",
  "computeMode": "cpu"
}
```

| Key | Meaning |
|---|---|
| `inputRoots` | Fixed input directories, as an array of path strings |
| `outputRoot` | Fixed master artifact directory |
| `huggingfaceToken` | Hugging Face token for model access |
| `computeMode` | `cpu` or `gpu` |

Product-owned defaults, such as supported audio extensions, live in runtime defaults and are not user settings.

## Output

Master output:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

Download ZIP:

```text
README.md
items/
  <item-id>/
    convert_info.json
    timeline.json
```

`timeline.json` is the primary artifact. It stores speaker labels, audio-relative timestamps, absolute timestamps when available, and phone tokens.

`convert_info.json` stores source fingerprint, model/runtime metadata, processing-flow metadata, counts, and output file names.

Source audio files are not included in the master output or download ZIP.

## Common CLI

| Purpose | Command |
|---|---|
| Start | `.\start.ps1` |
| Stop | `.\stop.ps1` |
| Settings status | `.\cli.ps1 settings status --json` |
| Add input directory | `.\cli.ps1 settings inputs add "C:\TimelineData\input-audio\" --json` |
| Set master output | `.\cli.ps1 settings master set "C:\TimelineData\audio" --json` |
| List source audio | `.\cli.ps1 files list --json` |
| Refresh changed items | `.\cli.ps1 items refresh --json` |
| Small test batch | `.\cli.ps1 items refresh --max-items 3 --json` |
| List generated items | `.\cli.ps1 items list --json` |
| Remove generated items | `.\cli.ps1 items remove --item-id item-a,item-b --dry-run --json` |
| Create ZIP | `.\cli.ps1 items download --json` |
| Model inventory | `.\cli.ps1 models list --json` |

For CLI JSON details, see [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md).

`runs` commands are diagnostic-only. Run directories are internal runtime files, not user-facing artifacts.

## Docker And Storage

In normal Windows operation, use `start.ps1`, `cli.ps1`, and `stop.ps1` rather than typing Docker commands directly.

| Location | User-facing | Purpose |
|---|---:|---|
| `settings.json` | Yes | Fixed input roots, output root, token, compute mode |
| `outputRoot` | Yes | Master item artifacts |
| `app-data` Docker volume | No | Run state, status, logs, catalog index |
| `cache-data` Docker volume | No | Hugging Face, Transformers, Torch, and model cache |
| `/tmp/...` inside container | No | Temporary staging and scratch work |

`uninstall.ps1` keeps `app-data`, `cache-data`, and `settings.json` by default. Use deletion options only when you intentionally want to delete them.

## Testing

Host Python CLI execution is blocked for normal use. Tests may use the explicit development override.

Normal checks:

```powershell
.\scripts\lint.ps1 -IncludeLocalCliDownload -IncludeOperationalSmoke
```

Full pipeline smoke with a real short audio file:

```powershell
.\scripts\test-operational.ps1 -UseRealModels -SourceAudioPath "C:\TimelineData\input-audio\sample.mp3" -KeepOutput
```

The real-model smoke test uses an isolated test workspace and does not modify the normal `settings.json`.

## Docs

| Document | Purpose |
|---|---|
| [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md) | CLI JSON output contract |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Pipeline and artifact details |
| [docs/OPERATIONAL_STABILITY.ja.md](docs/OPERATIONAL_STABILITY.ja.md) | Operational stability checklist |
| [docs/SECURITY_AND_SAFETY.md](docs/SECURITY_AND_SAFETY.md) | Safety boundaries and cleanup risks |
| [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md) | Model and runtime notes |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Third-party notices |
| [docs/MANUAL_RELEASE.md](docs/MANUAL_RELEASE.md) | Manual release procedure |

## Repo Layout

```text
configs/
docker/
docs/
scripts/
worker/
cli.ps1
start.ps1
stop.ps1
uninstall.ps1
settings.example.json
```

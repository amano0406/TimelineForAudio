# TimelineForAudio

`TimelineForAudio` is a local Docker-first CLI tool that reads configured audio directories and keeps speaker-attributed phone-token timeline artifacts up to date.

Japanese README: [README.ja.md](README.ja.md)

This product is CLI-only. There is no Web UI. The public surface is intentionally small: source audio paths, local settings, master artifacts, download ZIPs, and CLI JSON output. Internal run state, logs, model cache, and scratch files are product-managed implementation details.

## What It Does

- Reads audio files from configured input directories.
- Skips unchanged files when the source hash, source file identity, and generation signature are unchanged.
- Keeps the original audio-relative timeline while processing speech candidate ranges in smaller chunks.
- Runs required speaker diarization with `pyannote/speaker-diarization-community-1`.
- Extracts phone tokens with the current ZIPA large ONNX backend.
- Writes one master item directory per analyzed audio file.
- Builds a small handoff ZIP on demand.
- Exposes model inventory for license and usage-condition review.

## What It Does Not Do

- It does not provide a Web UI.
- It does not reconstruct readable text.
- It does not summarize meaning.
- It does not infer real speaker names, identity, age, gender, or attributes.
- It does not modify source audio files.
- It does not put processing scratch files in the master output.
- It does not treat run directories as user-facing download artifacts.

## Current Pipeline

1. Read audio files from configured input directories.
2. Normalize each audio file for processing without modifying the original file.
3. Detect speech candidate ranges and keep original audio-relative timestamps.
4. Run speaker diarization.
5. Extract phone tokens from speech candidate chunks.
6. Merge speaker turns, timestamps, and phone tokens into `timeline.json`.
7. Write `convert_info.json` with source, model, runtime, and processing-flow metadata.

Long recordings are not sent to ZIPA as one large inference request. Speech candidates are chunked internally and merged back to the original timeline.

## Settings

Normal Docker Compose operation uses the repo-root local settings file:

```text
C:\apps\TimelineForAudio\settings.json
```

The repo keeps a Git-managed template:

```text
C:\apps\TimelineForAudio\settings.example.json
```

`settings.json` is intentionally not committed. It is created from `settings.example.json` when missing.

Default shape:

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

User-controlled settings:

| Key | Meaning |
|---|---|
| `inputRoots` | Fixed source audio directories. Each entry is a path string. |
| `outputRoot` | Fixed master artifact directory. |
| `huggingfaceToken` | Local Hugging Face token for model access. |
| `computeMode` | `cpu` or `gpu`. |

Product-owned defaults, such as supported audio extensions, live in runtime defaults and are not user settings.

## Output Contract

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

`timeline.json` is the final structured audio timeline:

```json
{
  "schema_version": 1,
  "artifact_type": "timeline",
  "source": {},
  "pipeline": {},
  "turns": [
    {
      "start_sec": 12.34,
      "end_sec": 15.67,
      "speaker": "SPEAKER_00",
      "phone_tokens": "..."
    }
  ]
}
```

`convert_info.json` contains source fingerprint, model/runtime metadata, processing-flow metadata, counts, and output file names.

## Storage Model

| Location | Owner | Persistent | User-facing | Purpose |
|---|---|---:|---:|---|
| `settings.json` | User/local machine | Yes | Yes | Fixed input roots, output root, token, compute mode |
| `outputRoot` | User/downstream tools | Yes | Yes | Master item artifacts |
| `app-data` Docker volume | TimelineForAudio | Yes | No | Run state, status, logs, ETA history, catalog index |
| `cache-data` Docker volume | TimelineForAudio / model libraries | Yes | No | Hugging Face, Transformers, Torch, and model cache |
| `/tmp/...` inside container | TimelineForAudio | No | No | Temporary staging and scratch work |

Internal storage can change as long as the public output contract and CLI contract stay stable. The master output and download ZIP are the surfaces downstream products should rely on.

## CLI Usage

Run commands from the repository root:

```powershell
cd C:\apps\TimelineForAudio
```

On Windows, `*.ps1` scripts are the primary entrypoints. `*.bat` files are thin compatibility wrappers for environments that cannot launch PowerShell scripts directly, and must not define different behavior.

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --compute-mode gpu

.\cli.ps1 files list --json
.\cli.ps1 files list --page 1 --page-size 50 --json
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --max-items 3 --json
.\cli.ps1 items list --json
.\cli.ps1 items list --page 1 --page-size 50 --json
.\cli.ps1 items remove --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --dry-run --json
.\cli.ps1 items download --json
.\cli.ps1 items download --item-id item-a1b2c3d4e5f6,item-f6e5d4c3b2a1 --json
.\cli.ps1 runs list --json
.\cli.ps1 runs show --run-id <RUN_ID> --json
```

External application examples:

```cmd
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 settings status --json
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 files list --json
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File C:\apps\TimelineForAudio\cli.ps1 items refresh --json
```

When checking from WSL or Codex, call through the Windows command host:

```bash
cmd.exe /c "cd /d C:\apps\TimelineForAudio && powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File cli.ps1 settings status --json"
```

Notes:

- `items refresh` queues all changed files by default.
- Use `items refresh --max-items <N>` for smaller test or retry batches.
- Use `items refresh --reprocess-duplicates` only when you intentionally want to recompute unchanged files.
- `items remove` deletes managed item data and generated artifacts only. It does not delete source audio files.
- `runs` commands are diagnostic-only because run directories are product-managed runtime files.
- For CLI JSON output details, see [docs/CLI_OUTPUTS.ja.md](docs/CLI_OUTPUTS.ja.md).

Model inventory:

```powershell
.\cli.ps1 models list --json
.\cli.ps1 models list --include-remote --json
```

`--include-remote` asks the Hugging Face API for license, gated, and tag metadata. Treat the upstream model page as the final source of truth.

## Docker Compose

In normal Windows operation, use `start.ps1`, `cli.ps1`, and `stop.ps1` rather than typing Docker commands directly.

The Compose project name is:

```text
timeline-for-audio
```

The worker service runs the Python CLI. It exposes no browser port.

Docker resources:

- `app-data`: product-managed runtime data
- `cache-data`: model and library cache
- input roots: generated read-only bind mounts from `settings.json`
- `outputRoot`: generated writable bind mount from `settings.json`

GPU mode uses `docker-compose.gpu.yml` only when `settings.json` has `"computeMode": "gpu"` and an NVIDIA GPU is available from the shell.

Stop the worker:

```powershell
.\stop.ps1
```

Uninstall Docker resources:

```powershell
.\uninstall.ps1
```

`uninstall.ps1` keeps `app-data`, `cache-data`, and `settings.json` by default. Use deletion options only when you intentionally want to delete those.

## Testing

Host Python CLI execution is blocked for normal use. Tests may use the explicit development override.

Unit tests:

```bash
TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI=1 \
PYTHONPATH=/mnt/c/apps/TimelineForAudio/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForAudio/worker/tests -v
```

Docker checks:

```powershell
.\start.ps1
.\cli.ps1 settings status --json
.\cli.ps1 files list --json
.\cli.ps1 items refresh --max-items 1 --json
.\cli.ps1 items list --json
```

Local `cli.ps1` download smoke test:

```powershell
.\scripts\test-local-cli-download.ps1
```

Isolated operational smoke test:

```powershell
.\scripts\test-operational.ps1
```

This test creates a separate temporary settings file, points input and output to a generated test workspace, and leaves the normal `settings.json` untouched. By default it uses `items refresh --queue-only` and does not run the heavy models. Use real models only when you explicitly want to verify the full pipeline:

```powershell
.\scripts\test-operational.ps1 -UseRealModels -KeepOutput
```

When `-UseRealModels` is set, the test copies one small supported audio file from `settings.inputRoots` into the isolated test workspace. You can pin the source file explicitly when you want reproducible operational verification:

```powershell
.\scripts\test-operational.ps1 -UseRealModels -SourceAudioPath "C:\TimelineData\input-audio\sample.mp3" -KeepOutput
```

Include smoke tests after the Python checks:

```powershell
.\scripts\lint.ps1 -IncludeLocalCliDownload
.\scripts\lint.ps1 -IncludeOperationalSmoke
```

Operational stability notes: [docs/OPERATIONAL_STABILITY.ja.md](docs/OPERATIONAL_STABILITY.ja.md)

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

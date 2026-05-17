# Runtime

[Back to README](../README.md)

TimelineForAudio is a Docker-first local API product.

## Required Environment

- Windows PowerShell
- Docker Desktop
- `settings.json`
- Hugging Face token
- access approval for `pyannote/speaker-diarization-community-1`

FFmpeg and Python dependencies run inside Docker. The normal user does not need to install FFmpeg on the host.

## Settings

Local settings live at:

```text
C:\apps\TimelineForAudio\settings.json
```

The Git-managed template is:

```text
C:\apps\TimelineForAudio\settings.example.json
```

Current shape:

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    "C:\\TimelineData\\input-audio\\"
  ],
  "outputRoot": "C:\\TimelineData\\audio",
  "huggingFaceToken": "",
  "computeMode": "cpu",
  "runtime": {
    "instanceName": "ff4e43e190",
    "apiPort": 19100
  }
}
```

`huggingFaceToken` is the canonical token key. Older local files that still contain `huggingfaceToken` are read for compatibility and saved back using `huggingFaceToken`.

`runtime.instanceName` identifies this local Docker runtime. `runtime.apiPort` is used for the local worker API port.

Supported audio extensions are product-owned runtime defaults, not user settings.

## Local API

`start.ps1` starts the Docker worker. The worker exposes the local HTTP API used by Timeline.

The health endpoint is:

```text
GET http://127.0.0.1:<runtime.apiPort>/health
```

The response body is a JSON boolean: `true` or `false`.

## Storage

| Location | User-facing | Purpose |
|---|---:|---|
| `settings.json` | Yes | local input/output/token/compute configuration |
| `outputRoot` | Yes | durable master artifacts |
| `app-data` Docker volume | No | run state, status, logs, catalog index, ETA history |
| `cache-data` Docker volume | No | Hugging Face, Transformers, Torch, and model cache |
| container temp paths | No | scratch work for current processing |

`start.ps1`, `stop.ps1`, and normal API use should preserve Docker volumes.

`uninstall.ps1` is the cleanup entrypoint. Use its deletion options only when intentionally removing local runtime data.

## Worker Restart Behavior

If Docker or the worker stops while a run is `running`, that run is treated as interrupted.

On the next worker startup, the interrupted run is marked as `canceled` with `current_stage: "interrupted"` and is not resumed automatically. Run `items refresh` again to queue fresh work.

Runs that were still `pending` can still be picked up by the worker.

## Current Models

| Component | Current model / backend | Role |
|---|---|---|
| Speaker diarization | `pyannote/speaker-diarization-community-1` | assign mechanical speaker turns |
| Speech transcription | `Systran/faster-whisper-large-v3` via faster-whisper | transcribe source audio with automatic language detection |
| Speech candidate detection | FFmpeg silence detection | record speech-candidate ranges for processing metadata |

The public artifact stores Whisper transcript text in `text`. The transcript text is treated as the source of what was said; speaker diarization only adds mechanical speaker labels by timestamp overlap.

## GPU Mode

`computeMode: "gpu"` requires:

- NVIDIA GPU
- Docker GPU access
- GPU Docker worker flavor
- CUDA visible to PyTorch

If GPU checks fail, processing fails early instead of silently switching to CPU.

## First Run

The first run may download Docker image layers, Python dependencies, and model weights. Later runs reuse the Docker volumes unless they are explicitly removed.

## Local File Boundaries

TimelineForAudio is a local Docker worker plus API, not a hosted service or OS sandbox.

- source audio files are read from configured input directories
- source audio files are not deleted by item cleanup
- generated item cleanup removes selected master item directories
- run logs, locks, scratch files, and model caches are internal runtime data
- output ZIPs are written under the project `output` directory unless `--output` is specified
- Hugging Face tokens are stored in local-only `settings.json`, which is not tracked by Git

`items remove` deletes generated artifacts only. Use `--dry-run` first when selecting item IDs from another UI.

`uninstall.ps1` is broader and can remove Docker runtime data if requested. Use it only when cleaning the local installation.

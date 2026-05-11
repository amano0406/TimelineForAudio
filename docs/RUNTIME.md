# Runtime

[Back to README](../README.md)

TimelineForAudio is a Docker-first local CLI product.

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
  "huggingfaceToken": "",
  "computeMode": "cpu"
}
```

Supported audio extensions are product-owned runtime defaults, not user settings.

## Storage

| Location | User-facing | Purpose |
|---|---:|---|
| `settings.json` | Yes | local input/output/token/compute configuration |
| `outputRoot` | Yes | durable master artifacts |
| `app-data` Docker volume | No | run state, status, logs, catalog index, ETA history |
| `cache-data` Docker volume | No | Hugging Face, Transformers, Torch, and model cache |
| container temp paths | No | scratch work for current processing |

`start.ps1`, `stop.ps1`, and normal CLI use should preserve Docker volumes.

`uninstall.ps1` is the cleanup entrypoint. Use its deletion options only when intentionally removing local runtime data.

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

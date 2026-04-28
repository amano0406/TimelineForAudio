# TimelineForAudio v0.x.y Tech Preview

Local-first audio-to-IPA packaging tool for LLM workflows.
This is a desktop-style local tool, not a hosted SaaS product.

## Baseline Support

- Windows
- Docker Desktop
- CPU mode

## Optional Features

- GPU mode: NVIDIA + Docker GPU access required, supported via the GPU compose overlay
- Speaker diarization: optional, requires both a Hugging Face token and gated approval for `pyannote/speaker-diarization-community-1`

## Download

- Windows: `TimelineForAudio-windows-local.zip`
- WSL/Unix: backdoor Docker wrapper path

## What's New

- ...
- ...
- ...

## Known Limitations

- first run downloads models and takes time
- WSL/Unix wrappers are backdoor paths, not the Windows front door
- GPU is supported, but still requires NVIDIA + Docker GPU access
- the web UI has been removed; Docker CLI is the supported path
- Docker Desktop is required

## Verification

- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src` and `TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI=1`
- `scripts/lint.ps1` or `scripts/lint.sh`
- one real local smoke run
- `jobs archive` ZIP output confirmed

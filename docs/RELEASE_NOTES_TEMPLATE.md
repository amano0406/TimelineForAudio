# TimelineForAudio v0.x.y Tech Preview

Local-first audio-to-timeline packaging tool for LLM workflows.
This is a desktop-style local tool, not a hosted SaaS product.

## Baseline Support

- Windows
- Docker Desktop
- CPU mode

## Optional Features

- GPU mode: NVIDIA + Docker GPU access only, best-effort
- Speaker diarization: optional, requires both a Hugging Face token and gated approval for `pyannote/speaker-diarization-community-1`

## Download

- Windows: `TimelineForAudio-windows-local.zip`
- macOS: source-based, experimental path

## What's New

- ...
- ...
- ...

## Known Limitations

- first run downloads models and takes time
- macOS is experimental
- GPU is not the baseline support path
- GUI is the primary supported path
- Docker Desktop is required

## Verification

- `dotnet build web/TimelineForAudio.Web.csproj`
- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src`
- `scripts/test-e2e.ps1`
- one real local smoke run
- GUI ZIP download confirmed

# Testing

[Back to README](../README.md)

This document lists validation commands for the current API-first product.

## Lightweight Checks

Run from Windows PowerShell:

```powershell
.\scripts\lint.ps1 -IncludeLocalApiDownload -IncludeOperationalSmoke
```

This checks:

- Python unit tests
- C# health API build
- local API behavior
- Docker-facing JSON error envelopes
- settings and list commands
- download ZIP creation path

## Real-Model Smoke Test

Use a short real audio file:

```powershell
.\scripts\test-operational.ps1 -UseRealModels -SourceAudioPath "C:\TimelineData\input-audio\sample.mp3" -KeepOutput
```

The real-model smoke test uses an isolated workspace and does not modify the normal `settings.json`.

It verifies:

- real audio input
- real model execution
- refresh processing
- master artifact creation
- download ZIP creation
- second refresh skip behavior

## Host Worker Guard

Normal product use goes through Docker.

Host Python worker command execution is blocked unless the test environment explicitly opts in with:

```text
TIMELINE_FOR_AUDIO_ALLOW_HOST_RUN=1
```

## Release-Level Checks

Before a release, run:

```powershell
.\scripts\lint.ps1 -IncludeLocalApiDownload -IncludeOperationalSmoke
```

Run the real-model smoke test when model, Docker, GPU, pipeline, or artifact behavior changed.

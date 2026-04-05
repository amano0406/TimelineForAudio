# audio2timeline

Turn local audio files into timeline markdown packages that are easier to review, search, and hand to ChatGPT or other LLM tools.

[Japanese README](README.ja.md) | [Sample Timeline](docs/examples/sample-timeline.en.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [License](LICENSE)

## Overview

- local-first desktop-style tool
- audio-only pipeline, separate from `video2timeline`
- main operating path: Windows + Docker Desktop
- optimized for personal local use rather than broad end-user onboarding
- speaker diarization uses `pyannote/speaker-diarization-community-1`

## Current Capabilities

- input formats: `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`
- upload-first job creation from files or directories
- transcription with `faster-whisper`
- optional speaker diarization with `pyannote`
- deterministic transcript normalization with:
  - ASR initial prompt
  - glossary-based text normalization
- audio feature summaries for:
  - pause / silence
  - loudness
  - speaking rate
  - pitch
  - overlap / interruption
  - heuristic speaker confidence
  - heuristic diarization quality
- duplicate detection using both `source hash` and `conversion signature`
- rerun with same settings
- rerun with current settings
- ZIP export
- failure artifacts with `FAILURE_REPORT.md` and `logs/worker.log`

## Outputs

Each completed job produces per-item markdown artifacts and a ZIP handoff package.

Typical ZIP contents:

```text
audio2timeline-export.zip
  README.html
  TRANSCRIPTION_INFO.md
  timelines/
    2026-03-25 14-47-14.md
  raw-transcripts/
    2026-03-25 14-47-14.md
  normalized-transcripts/
    2026-03-25 14-47-14.md
  normalization-reports/
    2026-03-25 14-47-14.md
  speaker-summaries/
    2026-03-25 14-47-14.md
  audio-feature-summaries/
    2026-03-25 14-47-14.md
```

Open `README.html` first. It links to the per-item timeline, transcript, normalization, speaker, and feature files.

On partial failure, the export can also include:

- `FAILURE_REPORT.md`
- `logs/worker.log`

## Pipeline Summary

The current MVP pipeline is:

1. probe the source audio and compute `source hash`
2. normalize settings into a `conversion signature`
3. transcribe with `faster-whisper`
4. run diarization with `pyannote` when the Hugging Face prerequisites are available
5. derive pause, loudness, speaking-rate, pitch, overlap, and diarization heuristics
6. write:
   - `timeline.md`
   - raw transcript
   - normalized transcript
   - normalization report
   - speaker summary
   - audio feature summary
7. build the ZIP export

## Models And Runtime

- transcription backend: `faster-whisper`
- processing quality `standard`: `medium`
- processing quality `high`: `large-v3`
- diarization model: `pyannote/speaker-diarization-community-1`
- VAD / silence stack: `silero-vad` metadata plus `ffmpeg` silence detection

Compute modes:

- `CPU`
  - baseline path
  - works on more machines
  - slower
- `GPU`
  - optional
  - requires Docker access to a supported NVIDIA GPU
  - recommended for `high`

`high` quality is intended for a GPU with roughly 10 GB or more of VRAM. CPU `high` runs are allowed but much slower.

## Hugging Face Requirements

For the full diarization pipeline, save a Hugging Face token in `Settings` and make sure the account is authorized for `pyannote/speaker-diarization-community-1`.

If the token or approval is missing, the app can still transcribe audio, but diarization-dependent summaries will be unavailable.

## Quick Start

Windows:

```powershell
.\start.bat
```

macOS source-based helper:

```bash
./start.command
```

Then:

1. open `Settings`
2. save your Hugging Face token if you want diarization
3. choose `CPU` or `GPU`
4. choose `Standard` or `High`
5. optionally set:
   - transcription initial prompt
   - transcript normalization glossary
6. create a job from files or a directory
7. decide how to handle duplicates in the modal
8. wait for completion and download the ZIP

## Settings That Affect Reuse

Duplicate reuse is not based on file hash alone.

The app stores:

- `source hash`
- `conversion signature`

The `conversion signature` includes the effective pipeline version, model family, compute mode, processing quality, diarization enabled state, initial prompt hash, and normalization settings. That means the same source audio can be reprocessed when the conversion settings change.

## Metadata Stored Per Item

The current pipeline stores metadata such as:

- duration
- size bytes
- extension / container
- audio codec
- channels
- sample rate
- bitrate
- model id
- pipeline version
- conversion signature
- processing wall time
- stage elapsed times
- pause / silence summary
- loudness summary
- speaking-rate summary
- pitch summary
- speaker confidence summary
- optional voice-feature summary

## CLI

The GUI is the main entry point, but the worker CLI is available for direct use.

Common commands:

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

Example:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m audio2timeline_worker settings status
python -m audio2timeline_worker jobs list
python -m audio2timeline_worker jobs show --job-id job-YYYYMMDD-HHMMSS-xxxx
python -m audio2timeline_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxx
```

## Testing

Run worker unit tests:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

Build the Docker services:

```powershell
docker compose build web worker
```

## License

This repository is licensed under the MIT License. See [LICENSE](LICENSE).

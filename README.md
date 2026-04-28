# TimelineForAudio

TimelineForAudio is a local CLI tool that converts audio files into IPA-first artifacts.

[Japanese README](README.ja.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [License](LICENSE)

## Current Scope

The web UI has been removed. The supported interface is now the Python worker CLI.

The tool keeps the same core output idea:

- `IPA.md`
- `Readable Text.md`
- reduced ZIP handoff packages for either IPA or Readable Text

The original audio file is not included in export ZIP packages.

## What It Does

The CLI can:

- save local settings
- save a Hugging Face token for optional speaker diarization
- create a job from one or more audio files
- process the job locally
- list and inspect jobs
- create an IPA ZIP or Readable Text ZIP from a completed job

The main processing flow is:

1. normalize audio
2. transcribe speech into cleanup-oriented source text
3. align speaker turns when diarization is available
4. derive turn-level IPA as the canonical intermediate
5. optionally reconstruct readable text from IPA and context
6. write artifacts and export ZIP packages

## Requirements

- Python 3.11+
- FFmpeg available on PATH
- internet access on first run for model downloads
- optional Hugging Face token for speaker diarization
- optional NVIDIA GPU setup for GPU mode

Docker files are still present for the worker image, but direct CLI use is the simplest path.

## Quick Start

From the repository root:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m timeline_for_audio_worker settings status
python -m timeline_for_audio_worker settings save --language ja --compute-mode cpu
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3"
python -m timeline_for_audio_worker jobs list
```

For speaker diarization:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m timeline_for_audio_worker settings save --token hf_xxx --terms-confirmed
```

To create only IPA and skip readable-text reconstruction:

```powershell
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3" --ipa-only
```

To pass context for readable-text reconstruction:

```powershell
python -m timeline_for_audio_worker jobs create --file "C:\path\to\audio.mp3" --language ja --supplemental-context-file ".\context.txt"
```

## Common Commands

- `settings status`
- `settings save`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`

Examples:

```powershell
python -m timeline_for_audio_worker jobs show --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
python -m timeline_for_audio_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa
python -m timeline_for_audio_worker jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind readable-text
```

## Local Data

By default, the CLI stores app data under:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix-like environments: `~/.timeline-for-audio`

You can override this with environment variables:

- `TIMELINE_FOR_AUDIO_APPDATA_ROOT`
- `TIMELINE_FOR_AUDIO_OUTPUTS_ROOT`
- `TIMELINE_FOR_AUDIO_UPLOADS_ROOT`

Hugging Face token data is stored under the app data root in `secrets/huggingface.token`.

## Docker Worker

`start.bat` and `start.command` now only build and start the worker container. They do not open a browser.

```powershell
.\start.bat
```

GPU worker overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d worker
```

## Supported Input Formats

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`

Actual decoding depends on the FFmpeg build available in the runtime environment.

## ZIP Output

IPA ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `ipa/<captured-datetime>.md`

Readable Text ZIP:

- `README.html`
- `CONVERSION_INFO.md`
- `readable-text/<captured-datetime>.md`

Failure reports and worker logs are included when needed.

## Testing

Run worker tests:

```powershell
$env:PYTHONPATH=".\worker\src"
python -m unittest discover .\worker\tests
```

Run lint when the local tooling is available:

```powershell
.\scripts\lint.ps1
```

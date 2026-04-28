# TimelineForAudio

TimelineForAudio is a local CLI tool that converts audio files into IPA-first artifacts.

[Japanese README](README.ja.md) | [Third-Party Notices](THIRD_PARTY_NOTICES.md) | [Model and Runtime Notes](MODEL_AND_RUNTIME_NOTES.md) | [Security And Safety](docs/SECURITY_AND_SAFETY.md) | [License](LICENSE)

## Current Scope

The web UI has been removed. The supported interface is now the Python worker CLI executed inside Docker.

The tool keeps the same core output idea:

- `IPA.md`
- `Readable Text.md`
- reduced ZIP handoff packages for either IPA or Readable Text

The original audio file is not included in export ZIP packages.

## What It Does

The CLI can:

- save local settings
- manage fixed input directories and a fixed output directory
- save a Hugging Face token for optional speaker diarization
- refresh configured input directories
- skip unchanged audio files automatically
- create one-off jobs from one or more audio files
- process the job locally
- list and inspect jobs
- create an IPA ZIP or Readable Text ZIP from a completed job
- compare produced turn artifacts with reference JSON for lightweight quality checks

The main processing flow is:

1. normalize audio
2. transcribe speech into cleanup-oriented source text
3. align speaker turns when diarization is available
4. derive turn-level IPA as the canonical intermediate
5. optionally reconstruct readable text from IPA and context
6. write artifacts and export ZIP packages

## Requirements

- Docker Desktop
- Docker engine running
- internet access on first run for model downloads
- optional Hugging Face token for speaker diarization
- optional NVIDIA GPU setup for GPU mode

Normal CLI execution is allowed only inside the Docker container. Do not run
`python -m timeline_for_audio_worker ...` directly on the host for normal use.

Use `tfa.ps1` from PowerShell to execute the CLI inside Docker.

## Quick Start

From the repository root:

```powershell
.\start.ps1
.\tfa.ps1 settings init
.\tfa.ps1 settings status
.\tfa.ps1 settings save --language ja --compute-mode cpu
.\tfa.ps1 refresh
```

To run an IPA backend experiment:

```powershell
.\tfa.ps1 refresh --ipa-backend pyopenjtalk --ipa-only
```

The default IPA backend is `sudachi`. `pyopenjtalk` is experimental and requires the optional Python package to be available in the runtime.

To compare VAD behavior:

```powershell
.\tfa.ps1 refresh --vad-profile loose --ipa-only
.\tfa.ps1 refresh --vad-profile strict --ipa-only
```

The default VAD profile keeps the current 500 ms silence split. `loose` uses 1000 ms, and `strict` uses 250 ms.

For speaker diarization:

```powershell
.\tfa.ps1 settings save --token hf_xxx --terms-confirmed
```

To create only IPA and skip readable-text reconstruction:

```powershell
.\tfa.ps1 refresh --ipa-only
```

To pass context for readable-text reconstruction:

```powershell
.\tfa.ps1 refresh --language ja --supplemental-context-file ".\context.txt"
```

For a one-off file:

```powershell
.\tfa.ps1 jobs create --file "C:\path\to\audio.mp3"
```

## Common Commands

- `settings status`
- `settings init`
- `settings save`
- `settings input-root list/add/remove/clear`
- `settings output-root list/set`
- `scan`
- `refresh`
- `jobs create`
- `jobs list`
- `jobs show`
- `jobs run`
- `jobs archive`
- `evaluate`

Examples:

```powershell
.\tfa.ps1 jobs show --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
.\tfa.ps1 jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa
.\tfa.ps1 jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind readable-text
```

Lightweight evaluation for produced turn artifacts:

```powershell
.\tfa.ps1 evaluate --prediction ".\outputs\job-...\media\media-0001\ipa\ipa_turns.json" --reference ".\references\case-001-ipa.json" --json
.\tfa.ps1 evaluate --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --artifact-kind ipa --reference ".\references\case-001-ipa.json" --json
```

`evaluate` reports text CER, IPA error rate, speaker label accuracy, and a simple speaker time mismatch proxy. The speaker time metric is for regression comparison only; it is not a full DER implementation.

Reference fixture details are documented in [Evaluation Fixtures](docs/EVALUATION.md).

## Refresh

`refresh` reads the configured input directories and processes only audio files that need new output.

- Configure input directories with `settings input-root`.
- Configure the fixed output directory with `settings output-root set`.
- If the audio file and generation conditions are unchanged, the file is skipped.
- The skip decision uses `source hash + generation signature`.
- Markdown files inside export ZIPs use the captured datetime, or a datetime inferred from the source file name when available.

To inspect configured inputs without processing:

```powershell
.\tfa.ps1 scan
```

To queue work without immediately processing:

```powershell
.\tfa.ps1 refresh --queue-only
```

## Local Data

Persistent settings are stored in the repository root:

- `settings.example.json`: tracked example settings
- `settings.json`: local settings, not tracked by Git

Create `settings.json` when needed:

```powershell
.\tfa.ps1 settings init
```

By default, secrets and worker state are stored under:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix-like environments: `~/.timeline-for-audio`

You can override this with environment variables:

- `TIMELINE_FOR_AUDIO_APPDATA_ROOT`
- `TIMELINE_FOR_AUDIO_SETTINGS_PATH`
- `TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH`
- `TIMELINE_FOR_AUDIO_OUTPUTS_ROOT`
- `TIMELINE_FOR_AUDIO_UPLOADS_ROOT`

Hugging Face token data is not written to `settings.json`; it is stored under the app data root in `secrets/huggingface.token`.

## Docker Worker

`start.ps1` is the Windows front door. It starts the worker container without opening a browser. Docker Compose builds the image only when it is missing.

```powershell
.\start.ps1
```

Run the Docker CLI wrapper:

```powershell
.\tfa.ps1 settings status
```

`start.ps1` and `tfa.ps1` generate `.docker/docker-compose.paths.yml` from the
input/output directories in `settings.json`.

- Input directories are mounted read-only inside Docker.
- Output directories are mounted writable inside Docker.
- Missing input directories are not mounted and will appear as undiscovered or missing at scan time.
- After changing `settings input-root` or `settings output-root`, the next `tfa.ps1` run regenerates the mount definition.
- The generated `.docker/docker-compose.paths.yml` file is local-only and ignored by Git.

Compatibility and backdoor entries:

- `start.bat`, `tfa.bat`, and `stop.bat` are thin compatibility wrappers around the PowerShell scripts.
- `start.command` and `tfa.command` remain available as a WSL/Unix backdoor, but they are not the Windows front door.
- The WSL/Unix backdoor needs `pwsh` to generate Docker mounts from Windows-style settings paths. Without `pwsh`, it can run basic Docker CLI commands, but directory refresh should be done through PowerShell.

GPU worker overlay:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d worker
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
$env:TIMELINE_FOR_AUDIO_ALLOW_HOST_CLI="1"
python -m unittest discover .\worker\tests
```

Run lint when the local tooling is available:

```powershell
.\scripts\lint.ps1
```

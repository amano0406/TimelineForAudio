# App Spec

## Goal

`TimelineForAudio` converts local audio files into IPA-first outputs that can be reviewed locally or handed to ChatGPT or another LLM.

The supported interface is the Python worker CLI. The previous ASP.NET Core web UI has been removed.

The system prioritizes:

- IPA as the canonical intermediate
- CLI-driven local processing
- readable job output for LLM workflows
- local processing over cloud dependencies
- per-turn timestamps and speaker alignment

## App Model

- `worker`: Python CLI and worker daemon
- `docker compose`: optional worker container runtime
- coordination: filesystem job directories

## CLI Flow

1. save settings when needed
2. create a job from files, directories, or configured source roots
3. either process immediately or queue the job
4. inspect job status and artifacts
5. archive either IPA or Readable Text output

## Input Model

The CLI supports:

- `--file`
- `--directory`
- `--source-id`
- `--language`
- `--supplemental-context`
- `--supplemental-context-file`
- `--ipa-only`

Supported audio extensions:

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`

## Output Model

Every job writes:

- `request.json`
- `status.json`
- `result.json`
- `manifest.json`
- `RUN_INFO.md`
- `CONVERSION_INFO.md`
- `NOTICE.md`
- `README.html` in the reduced export package

Each processed media item writes:

- `source.json`
- `audio/normalized.wav`
- `audio/cut_map.json`
- `transcript/cleanup_source.json`
- `transcript/cleanup_source.md`
- `transcript/context_primary.txt`
- `transcript/context_secondary.txt` when provided
- `transcript/context_merged.txt`
- `transcript/context_report.json`
- `transcript/turns_source.json`
- `transcript/turns_source.md`
- `transcript/transcript_delta.json`
- `analysis/diarization_turns.json`
- `ipa/ipa_turns.json`
- `ipa/IPA.md`
- `readable-text/readable_text_turns.json` when readable text is enabled
- `readable-text/Readable Text.md` when readable text is enabled

Reduced export packaging writes:

- `README.html`
- `CONVERSION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- `ipa/*.md` for IPA export
- `readable-text/*.md` for Readable Text export

## Settings

Stored in app data:

- input roots
- output roots
- audio extensions
- compute mode
- language hint
- Hugging Face terms confirmation

Stored separately under app data:

- Hugging Face token

Default app data root:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix-like environments: `~/.timeline-for-audio`

## CPU / GPU

- CPU path is the baseline
- GPU path uses the dedicated NVIDIA Docker worker overlay or local CUDA-capable Python setup
- model selection is internal and not exposed as a quality lane

## Duplicate Handling

- duplicate key: `source hash + generation signature`
- default policy: reuse prior result when the generation signature matches
- reuse is automatic at the file level

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- diarization failures should not fail the whole job

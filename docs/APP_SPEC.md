# App Spec

## Goal

`TimelineForAudio` converts local audio files into IPA-first outputs that can be reviewed locally or handed to ChatGPT or another LLM.

The system prioritizes:

- simple input selection for the user
- IPA as the canonical intermediate
- readable job output for LLM workflows
- local processing over cloud dependencies
- per-turn timestamps and speaker alignment

## App Model

- `web`: ASP.NET Core Razor Pages
- `worker`: Python
- coordination: shared filesystem, not HTTP worker calls

## User Flow

1. open the GUI
2. choose one or more uploaded files or a mounted directory
3. optionally add supplemental context for readable-text reconstruction
4. start a job
5. open the job detail page
6. inspect `IPA` and `Readable Text`
7. download either the IPA ZIP or the Readable Text ZIP

## Input Model

v1 supports:

- upload-first multi-file selection
- mounted directories

The web app expands selected roots into concrete file items before writing `request.json`.

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
- `readable-text/readable_text_turns.json`
- `readable-text/Readable Text.md`

Reduced export packaging writes:

- `README.html`
- `CONVERSION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- `ipa/*.md` for IPA export
- `readable-text/*.md` for Readable Text export

## Progress Model

The GUI shows:

- `items_done / items_total`
- `current_stage`
- `current_item`
- `processed_duration_sec / total_duration_sec`
- elapsed time
- progress percent

ETA is optional and secondary. The primary progress contract is coarse progress plus per-file state.

## Settings

Stored in `app-data/settings.json`:

- input roots
- output roots
- audio extensions
- compute mode
- UI language
- Hugging Face terms confirmation

Stored separately in `app-data/secrets/huggingface.token`:

- Hugging Face token

## Profile

v1 keeps the UI simple:

- compute mode: `cpu` or `gpu`
- optional diarization
- optional job-level supplemental context text
- no user-visible quality lane selector

There is no free-form model picker in v1.

## CPU / GPU

- CPU path is implemented and is the public baseline
- GPU path is implemented through a dedicated NVIDIA-only Docker worker overlay
- internal model selection is not exposed as a user-facing quality concept

## Duplicate Handling

- duplicate key: `source hash + generation signature`
- default policy: reuse prior result when the generation signature matches
- reuse is automatic at the file level
- the user is not asked to choose reuse versus rerun during ordinary job creation

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- diarization failures should not fail the whole job
- speaker labels are turn-level alignment metadata, not identity guarantees

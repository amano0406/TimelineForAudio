# App Spec

## Goal

`TimelineForAudio` converts local audio files into timeline-oriented text and supporting summaries that can be handed to ChatGPT or another LLM.

The system prioritizes:

- simple input selection for the user
- readable job output for LLM workflows
- local processing over cloud dependencies
- preserving raw transcript artifacts alongside normalized output

## App Model

- `web`: ASP.NET Core Razor Pages
- `worker`: Python
- coordination: shared filesystem, not HTTP worker calls

## User Flow

1. open the GUI
2. choose one or more uploaded files or a mounted directory
3. review duplicate detection if it appears
4. start a job
5. open the job detail page
6. inspect `timeline.md`, transcript variants, and summaries
7. download the ZIP package

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
- `TRANSCRIPTION_INFO.md`
- `NOTICE.md`
- `README.html` in the reduced export package

Each processed media item writes:

- `source.json`
- `audio/normalized.wav`
- `audio/cut_map.json`
- `transcript/raw.json`
- `transcript/raw.md`
- `transcript/normalized.json`
- `transcript/normalized.md`
- `transcript/normalization_report.json`
- `transcript/normalization_report.md`
- `analysis/speaker_summary.json`
- `analysis/speaker_summary.md`
- `analysis/audio_features.json`
- `analysis/audio_features.md`
- `timeline/timeline.md`

Reduced export packaging writes:

- `README.html`
- `TRANSCRIPTION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- `timelines/*.md`
- `raw-transcripts/*.md`
- `normalized-transcripts/*.md`
- `normalization-reports/*.md`
- `speaker-summaries/*.md`
- `audio-feature-summaries/*.md`

## Progress Model

The GUI shows:

- `items_done / items_total`
- `current_stage`
- `current_item`
- `processed_duration_sec / total_duration_sec`
- `estimated_remaining_sec`
- elapsed time and stage elapsed time

ETA is derived from processed audio duration versus elapsed wall time.

## Settings

Stored in `app-data/settings.json`:

- input roots
- output roots
- audio extensions
- compute mode
- processing quality
- transcription initial prompt
- transcript normalization mode
- transcript normalization glossary
- Hugging Face terms confirmation

Stored separately in `app-data/secrets/huggingface.token`:

- Hugging Face token

## Profile

v1 keeps the UI simple:

- compute mode: `cpu` or `gpu`
- processing quality: `standard` or `high`
- optional diarization
- optional deterministic transcript normalization

There is no free-form model picker in v1.

## CPU / GPU

- CPU path is implemented and is the public baseline
- GPU path is implemented as an NVIDIA-only best-effort mode
- high quality requires GPU mode and enough VRAM

## Duplicate Handling

- duplicate key: `source hash + conversion signature`
- default policy: reuse prior result when the conversion signature matches
- optional override: reprocess duplicates with the same settings
- rerun can also use current settings to intentionally change the conversion signature

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- diarization failures should not fail the whole job
- speaker confidence and diarization quality are heuristic summaries, not identity guarantees

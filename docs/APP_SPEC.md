# App Spec

## Goal

`TimelineForAudio` converts local video files into timeline-oriented text that can be handed to ChatGPT or another LLM.

The system prioritizes:

- simple input selection for the user
- readable run output for LLM workflows
- local processing over cloud dependencies

## App Model

- `web`: ASP.NET Core Razor Pages
- `worker`: Python
- coordination: shared filesystem, not HTTP worker calls

## User Flow

1. open the GUI
2. choose one or more mounted input roots
3. optionally upload extra files
4. choose an output root
5. start a run
6. open the run detail page
7. inspect `timeline.md` for each media item

## Input Model

v1 supports:

- mounted directories
- multi-file uploads

The web app expands selected roots into concrete file items before writing `request.json`.

## Output Model

Every run writes:

- `request.json`
- `status.json`
- `result.json`
- `manifest.json`
- `RUN_INFO.md`
- `TRANSCRIPTION_INFO.md`
- `NOTICE.md`

Each processed media item writes:

- `source.json`
- `audio/trimmed.mp3`
- `audio/cut_map.json`
- `transcript/raw.json`
- `transcript/raw.md`
- `screen/screenshots.jsonl`
- `screen/screen_diff.jsonl`
- `timeline/timeline.md`

LLM export writes:

- `llm/timeline_index.jsonl`
- `llm/batch-*.md`

## Progress Model

The GUI shows:

- `videos_done / videos_total`
- `videos_skipped`
- `videos_failed`
- `current_stage`
- `current_media`
- `processed_duration_sec / total_duration_sec`
- `estimated_remaining_sec`

ETA is derived from processed media duration versus elapsed wall time.

## Settings

Stored in `app-data/settings.json`:

- input roots
- output roots
- video extensions
- Hugging Face terms confirmation

Stored separately in `app-data/secrets/huggingface.token`:

- Hugging Face token

## Profile

v1 uses a single fixed profile:

- `quality-first`

There is no user-facing model picker in v1.

## CPU / GPU

- CPU path is implemented
- GPU is intentionally shown as coming soon

## Duplicate Handling

- duplicate key: file SHA-256
- default policy: skip
- optional override: reprocess all duplicates

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- do not use GPL-dependent `simple-diarizer`

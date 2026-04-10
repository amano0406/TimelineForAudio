# App Spec

## Goal

`TimelineForAudio` converts local audio files into timeline-oriented text and supporting summaries that can be handed to ChatGPT or another LLM.

The system prioritizes:

- simple input selection for the user
- readable job output for LLM workflows
- local processing over cloud dependencies
- preserving pass1 artifacts alongside the final pass2 transcript

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
- `transcript/pass1.json`
- `transcript/pass1.md`
- `transcript/context_primary.txt`
- `transcript/context_secondary.txt` when provided
- `transcript/context_merged.txt`
- `transcript/context_report.json`
- `transcript/pass2.json`
- `transcript/pass2.md`
- `transcript/pass_diff.json`
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
- `pass1-transcripts/*.md`
- `pass2-transcripts/*.md`
- `context-docs/*.txt`
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
- Hugging Face terms confirmation

Stored separately in `app-data/secrets/huggingface.token`:

- Hugging Face token

## Profile

v1 keeps the UI simple:

- compute mode: `cpu` or `gpu`
- processing quality: `standard` or `high`
- optional diarization
- optional job-level supplemental context text

There is no free-form model picker in v1.

## CPU / GPU

- CPU path is implemented and is the public baseline
- GPU path is implemented through a dedicated NVIDIA-only Docker worker overlay
- high quality is available on both CPU and GPU
- CPU + high is an expert lane
- GPU + high is the recommended best-quality lane, with about 10 GiB+ VRAM as the practical target

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

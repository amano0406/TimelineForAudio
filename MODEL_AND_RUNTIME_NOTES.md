# Model and Runtime Notes

This document explains what `TimelineForAudio` downloads or expects at runtime and what users should know before running the app locally.

## Public Release Contract

The current public release line is `TimelineForAudio v0.3.4 Tech Preview`.

- baseline support is Windows + Docker Desktop + CPU mode
- macOS is an experimental source-based path
- GPU mode is available only on supported NVIDIA + Docker GPU setups and is best-effort, not baseline support
- this app is local-first and desktop-style, not a hosted SaaS service

## Models Used by the Worker

`TimelineForAudio` uses a local-first audio pipeline and downloads model/data assets only when they are actually needed.

Current main components:

- `faster-whisper`
  - transcription
  - timestamped segment generation
  - built-in VAD filtering during transcription
- `pyannote/speaker-diarization-community-1`
  - optional speaker diarization
- `librosa`
  - pitch and speaking-rate-adjacent feature extraction
- `ffmpeg`
  - decode, probing, and audio normalization

## First-Run Downloads

On first use, the worker may download:

- Python package dependencies
- Hugging Face model weights for transcription and diarization

These downloads are cached for reuse. The exact cache location depends on the runtime environment. In the Docker setup, cache volumes are mounted so the app does not need to download the same assets on every restart.

## Hugging Face Token and Gated Approval

Speaker diarization is optional, but if you want it, two things are required:

1. a Hugging Face access token
2. approval for the gated `pyannote/speaker-diarization-community-1` model page

Without those two conditions, the app does not fail the whole job. It continues with transcription and timeline generation, but without speaker diarization.

For the initial public release, this remains an optional feature, not part of the baseline support contract.

## Transcript Normalization Notes

The app preserves the raw transcript and can optionally create a normalized transcript variant.

Current normalization behavior:

- deterministic glossary-based text replacement
- deterministic speaker-label replacement
- separate normalization report generation

This is not an LLM rewrite pass. The raw transcript remains available for review and provenance checks.

## Audio Feature Notes

The app computes additional summaries from normalized audio and transcript timing, including:

- pause and silence summaries
- loudness summaries
- speaking-rate summaries
- pitch summaries
- overlap and interruption summaries
- heuristic speaker-confidence and diarization-quality summaries

These summaries are intended as review aids. They are not identity guarantees or ground-truth labels.

## Audio Preparation Notes

Inputs are normalized into a stable worker format before transcription.

- source files are decoded with `ffmpeg`
- normalized worker audio is written as mono `16kHz` WAV
- timing metadata remains inspectable through `source.json` and `cut_map.json`

## Intended Workflow

The generated output is designed to be reviewed locally, then compressed and uploaded to ChatGPT or another LLM for follow-up analysis.

Typical follow-up use cases:

- meeting review
- topic extraction
- communication analysis
- personal conversation review over time
- turning many local recordings into a structured prompt-ready archive

## Public Samples

The sample timelines in this repository are based on real generated output, but names and sensitive details are redacted.

- English sample: [docs/examples/sample-timeline.en.md](docs/examples/sample-timeline.en.md)
- Japanese sample: [docs/examples/sample-timeline.ja.md](docs/examples/sample-timeline.ja.md)

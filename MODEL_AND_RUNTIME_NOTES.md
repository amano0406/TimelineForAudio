# Model and Runtime Notes

This document explains what `TimelineForAudio` downloads or expects at runtime and what users should know before running the app locally.

## Public Release Contract

The current public release line is `TimelineForAudio v0.3.3 Tech Preview`.

- baseline support is Windows + Docker Desktop + CPU mode
- macOS is an experimental source-based path
- GPU mode is available only on supported NVIDIA + Docker GPU setups and is best-effort, not baseline support
- this app is local-first and desktop-style, not a hosted SaaS service

## Models Used by the Worker

`TimelineForAudio` uses a local-first pipeline and downloads model/data assets only when they are actually needed.

Current main components:

- `whisperx`
  - transcription
  - timestamp alignment
  - optional diarization integration
- `EasyOCR`
  - OCR for screenshots when a frame is important enough to inspect
- `pytesseract` / Tesseract
  - supplemental OCR backend
- `florence-community/Florence-2-base`
  - screenshot captioning / image description when screen changes are important
- `pyannote/speaker-diarization-community-1`
  - optional speaker diarization

## First-Run Downloads

On first use, the worker may download:

- Python package dependencies
- Hugging Face model weights
- OCR-related model/data files

These downloads are cached for reuse. The exact cache location depends on the runtime environment. In the Docker setup, cache volumes are mounted so the app does not need to download the same assets on every restart.

## Hugging Face Token and Gated Approval

Speaker diarization is optional, but if you want it, two things are required:

1. a Hugging Face access token
2. approval for the gated `pyannote/speaker-diarization-community-1` model page

Without those two conditions, the app does not fail the whole job. It continues with transcription and timeline generation, but without speaker diarization.

For the initial public release, this remains an optional feature, not part of the baseline support contract.

## OCR and Image Notes

The app does not run OCR or captioning on every frame.

Current behavior:

- frames are sampled from the video
- lightweight screen-diff logic classifies each frame change
- OCR and image-caption steps run only on the initial frame or on major screen changes
- minor cursor movement or trivial UI movement is intentionally suppressed

This keeps exported timelines smaller and more useful for LLM workflows.

## Silence Trimming

Silence trimming is used internally as a processing optimization.

- It can reduce unnecessary transcription work.
- It does not redefine the authoritative timeline.
- Final exported timeline entries are aligned back to original media time.
- `cut_map.json` is written so the mapping remains inspectable.

## Intended Workflow

The generated run output is designed to be reviewed locally, then compressed and uploaded to ChatGPT or another LLM for follow-up analysis.

Typical follow-up use cases:

- meeting review
- topic extraction
- communication analysis
- personal conversation review over time
- turning many local recordings into a structured corpus for downstream prompts

## Public Samples

The sample timelines in this repository are based on real generated output, but names and sensitive details are redacted.

- English sample: [docs/examples/sample-timeline.en.md](docs/examples/sample-timeline.en.md)
- Japanese sample: [docs/examples/sample-timeline.ja.md](docs/examples/sample-timeline.ja.md)

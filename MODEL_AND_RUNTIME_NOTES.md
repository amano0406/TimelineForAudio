# Model and Runtime Notes

This document explains the current runtime model choices and local execution contract for TimelineForAudio.

## Public Contract

TimelineForAudio is a local CLI worker. Windows PowerShell scripts are the primary entrypoint. WSL/macOS shell scripts are kept as developer/backdoor paths.

The worker does not reconstruct readable text, summarize meaning, or infer real speaker identities. It produces a structured timeline artifact that preserves the original audio timeline.

## Current Models

The current provisional model set is:

| Component | Current model / backend | Role |
| --- | --- | --- |
| Speaker diarization | `pyannote/speaker-diarization-community-1` | Generate mechanical speaker turns such as `SPEAKER_00` and `SPEAKER_01`. |
| Acoustic units | `anyspeech/zipa-large-crctc-300k` | Extract phone-like acoustic units from speech candidate audio. |
| Speech candidate detection | `ffmpeg silencedetect` | Avoid running heavier model work over obvious silence. |

The output contract intentionally uses `acoustic_units` instead of IPA, phoneme, or phone. The backend may change later without changing the primary artifact shape.

When `computeMode` is `gpu`, the worker must run as the GPU Docker flavor, PyTorch must see CUDA, and ZIPA ONNX Runtime must expose `CUDAExecutionProvider`. If any of these checks fail, the run fails early instead of silently falling back to CPU. The primary timeline artifact records the actual acoustic-unit execution provider.

## First-Run Downloads

On first use, the worker may download:

- Docker image layers
- Python package dependencies
- Hugging Face model weights for pyannote and ZIPA

Docker volumes cache model files so the same assets do not need to be downloaded on every run.

## Hugging Face Requirements

Speaker diarization is required. The user must configure:

1. a Hugging Face access token
2. approval for `pyannote/speaker-diarization-community-1`

If these prerequisites are missing, the item fails instead of silently producing fallback speaker labels. This is intentional because speaker labels are part of the main artifact.

## Audio Preparation

The worker:

1. decodes source audio through FFmpeg
2. writes normalized `16kHz mono` WAV for processing
3. detects silence with FFmpeg
4. creates speech candidate audio for heavier model stages
5. maps all turn timestamps back to the original audio timeline

The original source file is not modified.

## Main Artifact

The primary file is:

```text
<item-id>/timeline.json
```

It contains:

- source file metadata
- generation signature
- diarization backend/model metadata
- acoustic-unit backend/model metadata
- turn start/end time in source-audio-relative seconds
- optional absolute timestamp when recording origin can be inferred
- speaker label
- acoustic units

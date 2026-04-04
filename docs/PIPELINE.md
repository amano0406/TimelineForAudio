# Pipeline

## 1. Request Creation

The web app writes `request.json` into a new `run-*` directory under the selected output root.

The request contains:

- job id
- output root selection
- duplicate policy
- token-enabled flag
- fully expanded input items

## 2. Worker Pickup

The Python worker daemon scans enabled output roots for `run-*` directories whose `status.json` is still `pending`.

## 3. Preflight

For every input item:

- resolve the source path
- probe duration and file size with `ffprobe`
- compute SHA-256
- check duplicate state against `.audio2timeline/catalog.jsonl`

The worker writes `manifest.json` before heavy processing starts.

## 4. Audio

The worker:

1. extracts mono `16kHz` audio to `audio/extracted.mp3`
2. detects silence with `ffmpeg silencedetect`
3. trims silence with padding
4. writes `audio/cut_map.json`

The final timeline still uses original video timestamps.

## 5. Transcription

The worker calls `whisperx` with:

- model: `medium`
- language: `ja`
- device: `cpu`
- compute type: `int8`

Alignment is attempted when available.

If `pyannote` is available and the Hugging Face prerequisites are satisfied, diarization is applied.

## 6. Screen Extraction

Candidate frame timestamps are sampled across the video duration.

Each candidate frame is compared with the previous frame using:

- perceptual hash distance
- difference hash distance
- mean pixel difference
- changed pixel ratio

The result is classified as:

- `same`
- `minor_change`
- `major_change`

## 7. OCR And Caption

The worker only expands frames when:

- it is the first frame, or
- the frame is `major_change`

The current v1 stack is:

- OCR: `EasyOCR`
- caption: `Florence-2 base`

`same` and `minor_change` frames are intentionally compressed.

## 8. Timeline Rendering

`timeline.md` is rendered from:

- transcript segments
- original timestamps
- nearest earlier screen note
- matching screen diff summary

The main output shape is:

```md
## 00:00:12.345 - 00:00:15.678
Speech:
SPEAKER_01: ...

Screen:
...

Screen change:
...
```

## 9. LLM Export

After all media items finish, the worker builds:

- `llm/timeline_index.jsonl`
- `llm/batch-001.md`, `batch-002.md`, ...

These are grouped, text-only deliverables intended for direct LLM input.

## 10. Failure Model

- item-level failures do not abort the entire run
- the worker logs stack traces to `logs/worker.log`
- `status.json` and `result.json` are updated even on failure

# Pipeline

## 1. Request Creation

The web app writes `request.json` into a new `job-*` directory under the selected output root.

The request contains:

- job id
- output root selection
- duplicate policy
- token-enabled flag
- fully expanded input items
- compute mode and processing quality
- transcript normalization settings

## 2. Worker Pickup

The Python worker daemon scans enabled output roots for `job-*` directories whose `status.json` is still `pending`.

## 3. Preflight

For every input item:

- resolve the source path
- probe duration, codec, channels, sample rate, and file size with `ffprobe`
- compute SHA-256
- compute the conversion signature
- check duplicate state against `.timeline-for-audio/catalog.jsonl`

The worker writes `manifest.json` before heavy processing starts.

## 4. Audio Preparation

The worker normalizes each input into a stable analysis format:

1. decode the source audio with `ffmpeg`
2. write mono `16kHz` `audio/normalized.wav`
3. write `audio/cut_map.json`

In the current audio-only pipeline, `cut_map.json` is present for contract stability even when no trimming is applied.

## 5. Transcription

The worker calls `faster-whisper` with:

- model: `medium` for `standard`, `large-v3` for `high`
- language: `ja`
- device: `cpu` or `cuda`
- built-in VAD filtering
- optional `initial_prompt`

If GPU transcription fails, the worker can fall back to CPU and records a warning in the transcript metadata.

## 6. Optional Diarization

If `pyannote/speaker-diarization-community-1` is available and the Hugging Face prerequisites are satisfied, diarization is applied to the transcript segments.

If diarization is unavailable or fails:

- transcription still completes
- `diarization_used` stays false
- the error is recorded in transcript metadata

## 7. Transcript Normalization

The worker preserves the raw transcript, then optionally applies deterministic normalization:

- speaker label rewrites such as `speaker:SPEAKER_00 => Alice`
- text replacements such as `Open AI => OpenAI`
- context term tracking for the report

Artifacts written here:

- `transcript/raw.json`
- `transcript/raw.md`
- `transcript/normalized.json`
- `transcript/normalized.md`
- `transcript/normalization_report.json`
- `transcript/normalization_report.md`

## 8. Audio Analysis

The worker computes audio-oriented summaries from `audio/normalized.wav` and the normalized transcript:

- pause and silence summary
- loudness summary
- speaking rate summary
- pitch summary
- overlap and interruption summary
- speaker confidence summary
- diarization quality summary
- optional voice feature summary

Artifacts written here:

- `analysis/speaker_summary.json`
- `analysis/speaker_summary.md`
- `analysis/audio_features.json`
- `analysis/audio_features.md`

## 9. Timeline Rendering

`timeline.md` is rendered from:

- source metadata
- normalized transcript segments
- speaker summary
- audio feature summary

The main output shape is:

```md
# Audio Timeline

- Source: `...`
- Audio ID: `...`
- Duration: `...`
- Model: `...`
- Diarization used: `...`
- Transcript normalization mode: `...`

## Summary

- Speakers: `...`
- Silence seconds: `...`
- Loudness LUFS: `...`
- Estimated units/min: `...`
- Median pitch Hz: `...`
- Overlap segments: `...`
- Interruptions: `...`
- Speaker confidence mean ratio: `...`
- Diarization quality: `...`

## 00:00:12.345 - 00:00:15.678

- Speaker: `SPEAKER_01`
- Text: ...
- Pause before: `...`
- Overlap with previous: `...`
- Estimated units/min: `...`
```

## 10. Export Packaging

After the job finishes, the app can build a reduced review package containing:

- `README.html`
- `TRANSCRIPTION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- the per-item markdown artifacts grouped by type

`README.html` is the human entrypoint for exported results.

## 11. Failure Model

- item-level failures do not abort the entire job when other items can still complete
- the worker logs stack traces to `logs/worker.log`
- `status.json` and `result.json` are updated even on failure
- failed or warning jobs can still export successful artifacts plus failure diagnostics

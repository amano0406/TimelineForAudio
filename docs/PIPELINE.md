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
- job-level supplemental context text

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

## 5. Transcription Pass 1

The worker calls `faster-whisper` with:

- model: `medium` for `standard`, `large-v3` for `high`
- language: `ja`
- device: `cpu` or `cuda`
- built-in VAD filtering
- no diarization
- no user prompt injection

If GPU transcription fails, the worker can fall back to CPU and records a warning in the transcript metadata.

## 6. Context Builder

The worker builds deterministic plain-text context documents from:

- pass1 transcript cues
- extracted frequent terms and identifier-like tokens
- optional job-level supplemental context text

Artifacts written here:

- `transcript/context_primary.txt`
- `transcript/context_secondary.txt` when provided
- `transcript/context_merged.txt`
- `transcript/context_report.json`

## 7. Transcription Pass 2

The worker runs ASR on the same audio again, using `context_merged.txt` as the pass2 `initial_prompt`.

Artifacts written here:

- `transcript/pass1.json`
- `transcript/pass1.md`
- `transcript/pass2.json`
- `transcript/pass2.md`
- `transcript/pass_diff.json`

## 8. Diarization Enrichment

If `pyannote/speaker-diarization-community-1` is available and the Hugging Face prerequisites are satisfied, diarization runs after pass2.

The worker preloads the normalized audio with `torchaudio`, passes waveform + sample rate into `pyannote`, keeps the pass2 text fixed, and assigns speakers from diarization turns to pass2 timestamps for downstream timeline and summary generation.

If diarization is unavailable or fails:

- transcription still completes
- `diarization_used` stays false
- the error is recorded in transcript metadata

Artifacts written here:

- `transcript/pass2_words.json`
- `transcript/pass2_speaker_spans.json`
- `analysis/diarization_turns.json`

## 9. Audio Analysis

The worker computes audio-oriented summaries from `audio/normalized.wav` and the pass2 transcript:

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

## 10. Timeline Rendering

`timeline.md` is rendered from:

- source metadata
- pass2 speaker-attributed spans when available, otherwise pass2 transcript segments
- speaker summary
- audio feature summary

The main output shape is:

```md
# Audio Timeline

- Source: `...`
- Audio ID: `...`
- Duration: `...`
- Model: `...`
- Transcript source: `pass2`
- Supplemental context configured: `...`
- Diarization used: `...`

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

## 11. Export Packaging

After the job finishes, the app can build a reduced review package containing:

- `README.html`
- `TRANSCRIPTION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- the per-item markdown artifacts grouped by type

`README.html` is the human entrypoint for exported results.

## 12. Failure Model

- item-level failures do not abort the entire job when other items can still complete
- the worker logs stack traces to `logs/worker.log`
- `status.json` and `result.json` are updated even on failure
- failed or warning jobs can still export successful artifacts plus failure diagnostics

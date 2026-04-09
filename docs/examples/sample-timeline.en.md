# Public Sample Timeline

This sample is based on a real generated timeline, with names, organizations, and potentially sensitive content replaced by placeholders.

```md
# Audio Timeline

- Source: `/shared/inputs/example/customer-followup-call.wav`
- Audio ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`
- Model: `medium`
- Diarization used: `true`
- Transcript normalization mode: `deterministic`
- Normalized segments changed: `1`

## Summary

- Speakers: `2`
- Silence seconds: `3.284`
- Loudness LUFS: `-18.7`
- Estimated units/min: `169.2`
- Median pitch Hz: `188.4`
- Overlap segments: `1`
- Interruptions: `0`
- Speaker confidence mean ratio: `0.91`
- Diarization quality: `good`

## 00:00:11.179 - 00:00:57.194

- Speaker: `Speaker A`
- Text: Hello, this is [PERSON_A]. I am following up about the return request for [ITEM_GROUP_A]. I would like to confirm why the expected materials were missing from the package.
- Pause before: `0.000s`
- Overlap with previous: `0.000s`
- Estimated units/min: `161.0`

## 00:00:57.174 - 00:01:03.400

- Speaker: `Speaker B`
- Text: Understood. Sorry about that.
- Pause before: `0.000s`
- Overlap with previous: `0.020s`
- Estimated units/min: `38.5`
```

Notes:

- `timelines/*.md` keeps the timestamped timeline view.
- `raw-transcripts/*.md` preserves the pre-normalization transcript.
- `normalized-transcripts/*.md` shows any deterministic text or speaker-label cleanup.
- `audio-feature-summaries/*.md` carries pause, loudness, pitch, overlap, and related summaries.

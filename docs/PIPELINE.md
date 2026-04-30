# Pipeline

## 1. Request Creation

The CLI creates an internal run directory under the configured output root.

The request contains:

- run id
- output root
- input items
- compute mode
- duplicate policy
- generation signature
- Hugging Face token availability flag

Language hints and supplemental text are not used by this product.

## 2. Preflight

For every input item the worker:

- resolves the source path
- probes media metadata with `ffprobe`
- computes SHA-256
- checks duplicate state in `.timeline-for-audio/catalog.jsonl`
- writes `manifest.json`

The duplicate key is:

```text
source hash + generation signature + source file identity
```

`source file identity` includes the configured input root id and relative path. A renamed file is therefore treated as a different source.

`refresh` queues all changed files by default. `refresh --max-items <N>` limits one invocation when a smaller test or retry batch is safer.

## 3. Audio Preparation

The worker:

1. decodes the source audio with `ffmpeg`
2. writes `source/audio-normalized.wav`
3. detects speech candidate ranges
4. writes `segments/speech-candidate-map.json`
5. writes `segments/speech-candidates.json`

The original audio file is not modified. The worker does not build one large concatenated speech-candidate audio file for normal processing. Heavy model work reads short candidate ranges from `source/audio-normalized.wav` so long recordings do not need to be processed as one large chunk.

## 4. Speaker Diarization

Speaker diarization is required.

Current model:

```text
pyannote/speaker-diarization-community-1
```

Output:

```text
ai-raw/speaker-turns.raw.json
```

If diarization cannot run, the media item fails. The worker does not create fallback speakers.

## 5. Acoustic Unit Extraction

Current backend:

```text
anyspeech/zipa-large-crctc-300k via ONNX Runtime
```

Output:

```text
ai-raw/acoustic-units.raw.json
```

The output field is named `acoustic_units` rather than IPA, phoneme, or phone so that the backend can change without changing the product contract.

In GPU mode, ZIPA uses ONNX Runtime with `CUDAExecutionProvider` when it is available. The worker records the actual execution provider in `ai-raw/acoustic-units.raw.json` and in the primary timeline pipeline metadata.

Speech candidate ranges are processed in small chunks before being merged back into original timeline turns. This keeps long recordings from failing late because one large inference request exhausted memory.

## 6. Timeline Assembly

The worker aligns acoustic-unit spans to diarization turns by timestamp overlap.

Primary output:

```text
timeline/speaker-acoustic-units-timeline.json
```

Each turn contains:

- `start_sec`
- `end_sec`
- `absolute_start_at` when available
- `absolute_end_at` when available
- `speaker`
- `acoustic_units`
- `unit_type`
- `confidence`

## 7. Archive

`runs archive` exports the timeline JSON package.

The audio file itself is not embedded in the archive.

## 8. Performance Summary

Each finished run writes:

```text
RUN_PERFORMANCE.json
```

This file summarizes item counts, audio duration, wall time, stage totals, and completed-audio throughput. It is meant for operational tuning, not as a user-facing artifact.

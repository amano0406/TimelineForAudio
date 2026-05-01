# Pipeline

## 1. Request Creation

The CLI creates an internal temporary run directory under the worker runtime area.

The request contains:

- run id
- master output root
- input items
- compute mode
- duplicate policy
- generation signature
- Hugging Face token availability flag

Language hints and supplemental text are not used by this product.

For licensing and usage-condition checks, the CLI can list the current model inventory:

```text
models list --json
models list --include-remote --json
```

Remote metadata comes from the Hugging Face model API when requested.

## 2. Preflight

For every input item the worker:

- resolves the source path
- probes media metadata with `ffprobe`
- computes SHA-256
- checks duplicate state from existing master item artifacts
- writes `manifest.json`

The duplicate key is:

```text
source hash + generation signature + source file identity
```

`source file identity` includes the configured input root id and relative path. A renamed file is therefore treated as a different source.

`items refresh` queues all changed files by default. `items refresh --max-items <N>` limits one invocation when a smaller test or retry batch is safer.

The master directory is not used as a run-log store. It contains only completed item artifact directories. Runtime catalogs, logs, and locks are temporary and can be rebuilt or discarded.

## 3. Audio Preparation

The worker:

1. decodes the source audio with `ffmpeg`
2. creates a temporary normalized WAV for model processing
3. detects speech candidate ranges
4. keeps the speech candidate map in memory for the current item
5. removes temporary processing files after the item is written

The original audio file is not modified. The worker does not build one large concatenated speech-candidate audio file for normal processing. Heavy model work reads short candidate ranges from the temporary normalized WAV so long recordings do not need to be processed as one large chunk. Normalized audio and speech-candidate maps are processing intermediates, not master artifacts.

## 4. Speaker Diarization

Speaker diarization is required.

Current model:

```text
pyannote/speaker-diarization-community-1
```

If diarization cannot run, the media item fails. The worker does not create fallback speakers.

## 5. Phone Token Extraction

Current backend:

```text
anyspeech/zipa-large-crctc-300k via ONNX Runtime
```

The output field is named `phone_tokens`. TimelineForAudio stores phone-like tokens for downstream reconstruction, not readable text.

In GPU mode, ZIPA must use ONNX Runtime with `CUDAExecutionProvider`. If the GPU Docker flavor, CUDA-enabled PyTorch, or ONNX Runtime CUDA provider is unavailable, the run fails early instead of silently using CPU. The worker records the actual execution provider in the primary timeline pipeline metadata.

Speech candidate ranges are processed in small chunks before being merged back into original timeline turns. This keeps long recordings from failing late because one large inference request exhausted memory.

## 6. Timeline Assembly

The worker aligns phone-token spans to diarization turns by timestamp overlap.

Primary output:

```text
conversion-info.json
timeline.json
```

Each turn contains:

- `start_sec`
- `end_sec`
- `absolute_start_at` when available
- `absolute_end_at` when available
- `speaker`
- `phone_tokens`
- `unit_type`
- `confidence`

## 7. Item Download

`items download` exports timeline JSON packages for selected managed items.

The audio file itself is not embedded in the archive.

## 8. Performance Summary

Each finished run writes this file in the temporary run directory:

```text
RUN_PERFORMANCE.json
```

This file summarizes item counts, audio duration, wall time, stage totals, and completed-audio throughput. It is meant for operational tuning, not as a user-facing or master artifact.

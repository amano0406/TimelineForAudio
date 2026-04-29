# Pipeline

## 1. Request Creation

The CLI creates a `job-*` directory under the configured output root.

The request contains:

- job id
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

## 3. Audio Preparation

The worker:

1. decodes the source audio with `ffmpeg`
2. writes `source/audio-normalized.wav`
3. detects speech candidate ranges
4. writes `segments/speech-candidates.wav`
5. writes `segments/speech-candidate-map.json`
6. writes `segments/speech-candidates.json`

The original audio file is not modified.

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

Current provisional backend:

```text
ZIPA 300M
```

Output:

```text
ai-raw/acoustic-units.raw.json
```

The output field is named `acoustic_units` rather than IPA, phoneme, or phone so that the backend can change without changing the product contract.

In GPU mode, ZIPA uses ONNX Runtime with `CUDAExecutionProvider` when it is available. The worker records the actual execution provider in `ai-raw/acoustic-units.raw.json` and in the primary timeline pipeline metadata.

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

`jobs archive` exports the timeline JSON package.

The audio file itself is not embedded in the archive.

# Pipeline

[Back to README](../README.md)

## 1. Request Creation

The API asks the Docker worker to create an internal temporary run directory under the worker runtime area.

The request contains:

- run id
- master output root
- input items
- compute mode
- duplicate policy
- generation signature
- Hugging Face token availability flag

Language hints and supplemental text are not used by this product.

For licensing and usage-condition checks, the local API can list the current model inventory:

```text
POST /models/list
POST /models/list {"includeRemote": true}
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

`source file identity` includes the configured input root path and relative path. A renamed file is therefore treated as a different source.

`POST /items/refresh` queues changed files by default. The `maxItems` request field limits one invocation when a smaller test or retry batch is safer.

The master directory is not used as a run-log store. It contains only completed item artifact directories. Runtime catalogs, logs, and locks are temporary and can be rebuilt or discarded.

## 3. Audio Preparation

The worker:

1. decodes the source audio with `ffmpeg`
2. creates a temporary normalized WAV for model processing
3. detects speech candidate ranges
4. keeps the speech candidate map in memory for the current item
5. removes temporary processing files after the item is written

The original audio file is not modified. The speech-candidate map is kept as processing metadata; Whisper transcription reads the normalized audio so transcript text is not lost because of an overly aggressive silence cut. Normalized audio and speech-candidate maps are processing intermediates, not master artifacts.

## 4. Speaker Diarization

Speaker diarization is required.

Current model:

```text
pyannote/speaker-diarization-community-1
```

If diarization cannot run, the media item fails. The worker does not create fallback speakers.

## 5. Speech Transcription

Current backend:

```text
Systran/faster-whisper-large-v3 via faster-whisper
```

Whisper runs with automatic language detection. `settings.json` does not contain a language setting.

Whisper transcript text is the source of what was said. Speaker diarization is used only to add speaker labels by timestamp overlap.

The worker must not summarize, rewrite, or drop Whisper transcript text while assigning speakers. If the transcript text changes during timeline assembly, processing fails.

## 6. Timeline Assembly

The worker assigns speakers to Whisper transcript segments by timestamp overlap.

Primary output:

```text
convert_info.json
timeline.json
```

Each turn contains:

- `start_sec`
- `end_sec`
- `absolute_start_at` when available
- `absolute_end_at` when available
- `speaker`
- `text`
- transcription confidence metadata when available

## 7. Item Download

`POST /items/download` exports timeline JSON packages for selected managed items.

The audio file itself is not embedded in the archive.

## 8. Performance Summary

Each finished run writes this file in the temporary run directory:

```text
RUN_PERFORMANCE.json
```

This file summarizes item counts, audio duration, wall time, stage totals, and completed-audio throughput. It is meant for operational tuning, not as a user-facing or master artifact.

# Output Contract

[Back to README](../README.md)

TimelineForAudio creates durable master artifacts under the configured `outputRoot`.

Current `outputRoot`:

```text
C:\apps\Timeline\data\to_text\audio
```

## Master Directory

Each completed item is stored as one directory:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

Only completed item artifact directories belong in the master directory.

Run logs, locks, queue state, model caches, and temporary files are internal runtime data and should not be treated as public output.

## Item ID

`<item-id>` is stable for the generated artifact identity. It is derived from source context and file identity, not from the transcript text.

Example:

```text
20230219022348-dad740d2
```

Downstream callers should treat the item ID as an opaque identifier.

## Shared `source` Object

Both `timeline.json` and `convert_info.json` include a `source` object.

Representative shape:

```json
{
  "schema_version": 1,
  "file_name": "20230219022348.wav",
  "display_name": "20230219022348.wav",
  "original_path": "C:\\apps\\Timeline\\data\\input\\audio\\20230219022348.wav",
  "source_kind": "configured_directory",
  "source_id": "C:\\apps\\Timeline\\data\\input\\audio",
  "source_relative_path": "20230219022348.wav",
  "source_file_identity": "C:\\apps\\Timeline\\data\\input\\audio::20230219022348.wav",
  "source_hash": "64-char-sha256-hex",
  "size_bytes": 1234567,
  "duration_sec": 42.125,
  "container_name": "wav",
  "extension": ".wav",
  "audio_codec": "pcm_s16le",
  "audio_channels": 1,
  "audio_sample_rate": 16000,
  "bitrate": 256000,
  "recorded_at": "2023-02-19T02:23:48+09:00",
  "recorded_at_source": "filename",
  "recorded_at_timezone": "Asia/Tokyo"
}
```

Important fields:

| Field | Meaning |
|---|---|
| `file_name` | Source file basename. |
| `original_path` | Host-side source path from the configured input root. |
| `source_id` | Configured input root that discovered the file. |
| `source_relative_path` | Path relative to the configured input root. |
| `source_file_identity` | Stable source identity used for duplicate/change detection. |
| `source_hash` | SHA-256 of the source audio bytes. |
| `duration_sec` | Source audio duration in seconds. |
| `recorded_at` | Absolute recording time when inferred from metadata or filename. Otherwise `null`. |
| `recorded_at_source` | `metadata`, `filename`, or `unknown`. |

## `timeline.json`

`timeline.json` is the primary downstream artifact. It contains source metadata, pipeline identity, and speaker-separated transcript turns.

Abridged shape:

```json
{
  "schema_version": 1,
  "artifact_type": "timeline",
  "source": {
    "file_name": "20230219022348.wav",
    "source_file_identity": "C:\\apps\\Timeline\\data\\input\\audio::20230219022348.wav",
    "source_hash": "64-char-sha256-hex",
    "duration_sec": 42.125,
    "recorded_at": "2023-02-19T02:23:48+09:00"
  },
  "pipeline": {
    "pipeline_version": "2026-05-11-v1-whisper-transcript-timeline",
    "generation_signature": "64-char-sha256-hex",
    "speaker_backend": "pyannote.audio",
    "speaker_model_id": "pyannote/speaker-diarization-community-1",
    "transcription_backend": "faster-whisper-large-v3-v1",
    "transcription_model_id": "Systran/faster-whisper-large-v3",
    "transcription_language": "ja",
    "transcription_device": "cuda",
    "transcription_compute_type": "float16"
  },
  "turn_count": 2,
  "turns": [
    {
      "index": 1,
      "start_sec": 0.0,
      "end_sec": 2.42,
      "absolute_start_at": "2023-02-19T02:23:48+09:00",
      "absolute_end_at": "2023-02-19T02:23:50.420000+09:00",
      "speaker": "SPEAKER_00",
      "text": "Hello.",
      "transcription_segment_index": 1,
      "avg_logprob": -0.21,
      "no_speech_probability": 0.03
    },
    {
      "index": 2,
      "start_sec": 2.42,
      "end_sec": 5.8,
      "absolute_start_at": "2023-02-19T02:23:50.420000+09:00",
      "absolute_end_at": "2023-02-19T02:23:53.800000+09:00",
      "speaker": "SPEAKER_01",
      "text": "Thank you.",
      "transcription_segment_index": 2,
      "avg_logprob": -0.18,
      "no_speech_probability": 0.01
    }
  ]
}
```

Turn fields:

| Field | Meaning |
|---|---|
| `index` | 1-based order in the final timeline. |
| `start_sec` / `end_sec` | Source-audio-relative time range in seconds. |
| `absolute_start_at` / `absolute_end_at` | Absolute timestamps when `source.recorded_at` is known. Otherwise `null`. |
| `speaker` | Mechanical diarization label such as `SPEAKER_00`. This is not a real person name. |
| `text` | Whisper transcript text. TimelineForAudio does not summarize or rewrite it. |
| `transcription_segment_index` | Original transcription segment index when available. |
| `avg_logprob` | Transcription confidence signal from the backend. |
| `no_speech_probability` | Backend probability that the segment is non-speech. |

Downstream products should usually read `timeline.json` first.

## `convert_info.json`

`convert_info.json` explains how the item was generated. It is intended for audit, debugging, reproducibility, and model/license review.

Abridged shape:

```json
{
  "schema_version": 1,
  "artifact_type": "convert_info",
  "application": "TimelineForAudio",
  "generated_at": "2026-05-14T04:42:00+09:00",
  "source": {
    "file_name": "20230219022348.wav",
    "source_file_identity": "C:\\apps\\Timeline\\data\\input\\audio::20230219022348.wav",
    "source_hash": "64-char-sha256-hex",
    "duration_sec": 42.125
  },
  "pipeline": {
    "pipeline_version": "2026-05-11-v1-whisper-transcript-timeline",
    "generation_signature": "64-char-sha256-hex",
    "compute_mode": "gpu",
    "speech_activity_detection": {
      "backend": "ffmpeg-silencedetect",
      "model_id": "ffmpeg-silencedetect-noise-35db",
      "profile": "default",
      "parameters": {
        "min_silence_duration_ms": 500
      }
    },
    "speaker_diarization": {
      "required": true,
      "backend": "pyannote.audio",
      "model_id": "pyannote/speaker-diarization-community-1",
      "status": "ok",
      "turn_count": 12,
      "warning_count": 0
    },
    "speech_transcription": {
      "backend": "faster-whisper-large-v3-v1",
      "model_id": "Systran/faster-whisper-large-v3",
      "status": "ok",
      "language": "ja",
      "language_probability": 0.98,
      "device": "cuda",
      "compute_type": "float16",
      "segment_count": 8,
      "warning_count": 0
    }
  },
  "processing_flow": [
    {
      "step": 1,
      "name": "audio_normalization",
      "description": "Decode source audio into the worker's analysis format.",
      "persistent_output": false
    },
    {
      "step": 2,
      "name": "speech_activity_detection",
      "description": "Find source-audio ranges that are likely to contain speech.",
      "persistent_output": false
    },
    {
      "step": 3,
      "name": "speaker_diarization",
      "description": "Assign mechanical speaker labels to source-audio time ranges.",
      "persistent_output": false
    },
    {
      "step": 4,
      "name": "speech_transcription",
      "description": "Transcribe source audio with Whisper automatic language detection.",
      "persistent_output": false
    },
    {
      "step": 5,
      "name": "timeline_merge",
      "description": "Merge speaker labels, timestamps, and Whisper transcript text into the final timeline JSON without rewriting transcript text.",
      "persistent_output": true
    }
  ],
  "counts": {
    "speech_candidate_ranges": 4,
    "speaker_turns": 12,
    "transcript_segments": 8
  },
  "output_files": {
    "convert_info": "convert_info.json",
    "timeline": "timeline.json"
  }
}
```

Important fields:

| Field | Meaning |
|---|---|
| `generated_at` | Time the artifact was generated. |
| `pipeline.pipeline_version` | Human-readable processing pipeline version. |
| `pipeline.generation_signature` | Hash representing pipeline, model, VAD, compute, and artifact schema inputs. |
| `pipeline.compute_mode` | `cpu` or `gpu`. |
| `speech_activity_detection` | VAD backend and parameters. |
| `speaker_diarization` | Required diarization backend, model, status, and turn count. |
| `speech_transcription` | Transcription backend, model, language, device, and segment count. |
| `processing_flow` | Ordered processing steps. Only `timeline_merge` persists as a public output. |
| `counts` | Source processing counts used for sanity checks. |

## Download ZIP

`items download` creates a handoff ZIP:

```text
README.md
items/
  <item-id>/
    convert_info.json
    timeline.json
```

The ZIP does not contain source audio files, model caches, run logs, or temporary processing data.

The ZIP item files are the same public JSON artifacts from the master directory.

## Source File Identity

The same audio bytes with a different source path can be treated as a different source item.

This is intentional because file names and directory context can carry useful information for downstream products.

Duplicate/change detection uses:

- `source_file_identity`
- `source_hash`
- `generation_signature`

If the source bytes are unchanged but pipeline settings or model signatures change, the item can be treated as needing regeneration.

# Output Contract

[Back to README](../README.md)

TimelineForAudio creates durable master artifacts under the configured `outputRoot`.

## Master Directory

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

Only completed item artifact directories belong in the master directory.

Run logs, locks, queue state, caches, and temporary files are internal runtime data and should not be treated as public output.

## `timeline.json`

`timeline.json` is the primary artifact.

It contains:

- source file metadata
- generation signature
- diarization backend and model metadata
- transcription backend and model metadata
- source-audio-relative timestamps
- optional absolute timestamps when recording origin can be inferred
- mechanical speaker labels such as `SPEAKER_00`
- transcript text
- speech and non-speech timeline ranges when available

Speaker labels are not real names. The product does not infer identity, gender, age, role, or attributes.

## `convert_info.json`

`convert_info.json` explains how the item was created.

It contains:

- product name and version
- source fingerprint
- source file identity
- model/runtime metadata
- compute mode
- processing-flow metadata
- generation signature
- artifact names
- item counts and duration metadata

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

## Source File Identity

The same audio bytes with a different source path can be treated as a different source item.

This is intentional because file names and directory context can carry useful information for downstream products.

# App Spec

TimelineForAudio is a local CLI product for building speaker-attributed acoustic-unit timelines from configured audio directories.

## Scope

In scope:

- configured input directories
- configured output directory
- refresh-based processing
- duplicate skipping
- speech candidate detection
- required speaker diarization
- acoustic-unit extraction
- JSON timeline artifact generation

Out of scope:

- readable text restoration
- LLM calls
- summaries
- speaker identity inference
- IPA-specific product contract
- web UI

## Primary Artifact

```text
media/<media-id>/timeline/speaker-acoustic-units-timeline.json
```

This artifact is the product contract.

## Speaker Policy

The worker labels speakers as `SPEAKER_00`, `SPEAKER_01`, and so on.

It does not infer:

- real names
- gender
- age
- role
- identity

## Time Policy

All turn timestamps are audio-relative.

When a plausible recording start datetime is available, the worker also writes absolute timestamps. Filename-derived datetimes are treated as Asia/Tokyo unless metadata gives a more specific source.

## Reuse Policy

A file can be skipped only when all of these match:

- source hash
- generation signature
- source file identity

Source file identity includes the configured input root and relative path, so renamed files are new files even if the bytes match.

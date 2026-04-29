# Evaluation

The evaluator compares produced turn JSON with a reference JSON.

Default artifact kind:

```text
timeline
```

Default resolved path:

```text
media/<media-id>/timeline/speaker-acoustic-units-timeline.json
```

Metrics:

- text CER when reference text exists
- acoustic unit error rate when reference acoustic units exist
- speaker label accuracy when reference speakers exist
- lightweight speaker time mismatch proxy

This is a regression helper. It is not a full diarization error rate implementation.

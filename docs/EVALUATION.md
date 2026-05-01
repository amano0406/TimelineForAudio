# Evaluation

The evaluator compares produced turn JSON with a reference JSON.

Default artifact kind:

```text
timeline
```

Default resolved path:

```text
<item-id>/timeline.json
```

Metrics:

- text CER when reference text exists
- phone-token error rate when reference phone tokens exist
- speaker label accuracy when reference speakers exist
- lightweight speaker time mismatch proxy

This is a regression helper. It is not a full diarization error rate implementation.

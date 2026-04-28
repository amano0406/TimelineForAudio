# Evaluation Fixtures

`evaluate` compares generated turn artifact JSON with a reference JSON.

The reference JSON should use this shape:

```json
{
  "turns": [
    {
      "start": 0.0,
      "end": 1.2,
      "speaker": "SPEAKER_00",
      "text": "こんにちは",
      "ipa": "/konnitɕiwa/"
    }
  ]
}
```

Supported turn fields:

- `start` / `end`: audio-relative seconds
- `speaker`: expected speaker label
- `text`: expected readable text
- `ipa`: expected IPA text

The evaluator also accepts `speaker_segments`, `segments`, `ipa_turns`, `readable_text_turns`, or `diarization_turns` as the turn array key.

## Commands

Evaluate a direct artifact path:

```powershell
.\tfa.ps1 evaluate --prediction ".\outputs\job-...\media\media-0001\ipa\ipa_turns.json" --reference ".\references\case-001.json" --json
```

Evaluate by job:

```powershell
.\tfa.ps1 evaluate --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx --media-id media-0001 --artifact-kind ipa --reference ".\references\case-001.json" --json
```

If the job has exactly one media item, `--media-id` can be omitted.

Supported `--artifact-kind` values:

- `ipa`
- `readable-text`
- `turns-source`
- `diarization`

When `--job-id` is used, the CLI writes:

- `evaluation/<media-id>-<artifact-kind>/evaluation.json`
- `evaluation/<media-id>-<artifact-kind>/EVALUATION.md`

Use `--output-dir` to write the report elsewhere.

## Metrics

- `text.cer`: character error rate after whitespace removal
- `ipa.error_rate`: edit-distance rate over normalized IPA text
- `speaker.label_accuracy`: turn-pair speaker label match rate
- `speaker.time_mismatch_rate`: lightweight midpoint-based speaker timing mismatch proxy

`speaker.time_mismatch_rate` is for regression checks only. It is not full DER.

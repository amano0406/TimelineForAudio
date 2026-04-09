# 公開用サンプルタイムライン

このサンプルは、実際に生成されたタイムラインを元にしつつ、名前、組織名、商品名などを置き換えて公開用に調整したものです。

```md
# Audio Timeline

- Source: `/shared/inputs/example/customer-followup-call.wav`
- Audio ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`
- Model: `medium`
- Diarization used: `true`
- Transcript normalization mode: `deterministic`
- Normalized segments changed: `1`

## Summary

- Speakers: `2`
- Silence seconds: `3.284`
- Loudness LUFS: `-18.7`
- Estimated units/min: `169.2`
- Median pitch Hz: `188.4`
- Overlap segments: `1`
- Interruptions: `0`
- Speaker confidence mean ratio: `0.91`
- Diarization quality: `good`

## 00:00:11.179 - 00:00:57.194

- Speaker: `Speaker A`
- Text: こんにちは、[PERSON_A] です。[ITEM_GROUP_A] の返品について確認したくてご連絡しました。荷物に必要な資料が入っていなかった理由を確認したいです。
- Pause before: `0.000s`
- Overlap with previous: `0.000s`
- Estimated units/min: `161.0`

## 00:00:57.174 - 00:01:03.400

- Speaker: `Speaker B`
- Text: 承知しました。失礼しました。
- Pause before: `0.000s`
- Overlap with previous: `0.020s`
- Estimated units/min: `38.5`
```

ポイント:

- `timelines/*.md` には、タイムスタンプ付きの最終タイムラインが入ります
- `raw-transcripts/*.md` には、正規化前の transcript を残します
- `normalized-transcripts/*.md` には、deterministic な表記補正後の transcript を出します
- `audio-feature-summaries/*.md` には、pause、loudness、pitch、overlap などの要約が入ります

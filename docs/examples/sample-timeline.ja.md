# 公開用サンプルタイムライン

このサンプルは、実際に生成されたタイムラインを元にしつつ、名前、組織名、商品名などを置き換えて公開用に調整したものです。

```md
# Video Timeline

- Source: `/shared/inputs/example/customer-followup-call.mp4`
- Media ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`

## 00:00:11.179 - 00:00:57.194
Speech:
SPEAKER_00: こんにちは、[PERSON_A] です。[ITEM_GROUP_A] の返品について確認したくてご連絡しました。荷物に必要な資料が入っていなかった理由を確認したいです。

Screen:
OCR detected text. Top lines: もう少し詳しく入力してください / 音声認識では拾えませんでした / OBS 32.0.4 - Profile: Untitled

Screen change:
Initial frame.

## 00:00:57.174 - 00:01:03.400
Speech:
SPEAKER_00: 承知しました。失礼しました。

Screen:
No major screen changes detected.

Screen change:
Omitted.
```

ポイント:

- `Speech:` には、その時間帯の発話内容がまとまります
- `Screen:` には、OCR と画面説明の要約が入ります
- `Screen change:` には、前のフレームから意味のある変化があったかを入れます
- 元動画のタイムスタンプは保持されます

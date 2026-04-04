# Public Sample Timeline

This sample is based on a real generated timeline, with names, organizations, and potentially sensitive content replaced by placeholders.

```md
# Video Timeline

- Source: `/shared/inputs/example/customer-followup-call.mp4`
- Media ID: `2026-03-09-12-15-56-example`
- Duration: `70.417s`

## 00:00:11.179 - 00:00:57.194
Speech:
SPEAKER_00: Hello, this is [PERSON_A]. I am following up about the return request for [ITEM_GROUP_A]. I would like to confirm why the expected materials were missing from the package.

Screen:
OCR detected text. Top lines: Please add more detail / Speech recognition did not catch that / OBS 32.0.4 - Profile: Untitled

Screen change:
Initial frame.

## 00:00:57.174 - 00:01:03.400
Speech:
SPEAKER_00: Understood. Sorry about that.

Screen:
No major screen changes detected.

Screen change:
Omitted.
```

Notes:

- `Speech:` keeps the transcript grouped by time range.
- `Screen:` summarizes OCR and caption output instead of dumping full OCR every time.
- `Screen change:` tells you whether the frame introduced meaningful visual change.
- Original video timestamps are preserved.

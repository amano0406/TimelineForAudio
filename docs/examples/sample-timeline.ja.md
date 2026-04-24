# 公開用サンプル成果物

このサンプルは、実際に生成された成果物を元にしつつ、名前、組織名、商品名などを置き換えて公開用に調整したものです。

```md
# IPA

- File: `2026-03-09 12-15-56`
- Source File: `customer-followup-call.wav`
- Speakers: `2`
- Language Hint: `en`

## Turn 001

Time: `00:00:11.179 - 00:00:57.194`
Speaker: `SPEAKER_00`
IPA: `/həˈloʊ ðɪs ɪz .../`

## Turn 002

Time: `00:00:57.174 - 00:01:03.400`
Speaker: `SPEAKER_01`
IPA: `/ˌʌndɚˈstʊd .../`
```

```md
# Readable Text

- File: `2026-03-09 12-15-56`
- Source File: `customer-followup-call.wav`
- Speakers: `2`
- Language Hint: `en`

### Turn 001
Time: `00:00:11.179 - 00:00:57.194`
Speaker: `SPEAKER_00`
Text: こんにちは、[PERSON_A] です。[ITEM_GROUP_A] の返品について確認したくてご連絡しました。荷物に必要な資料が入っていなかった理由を確認したいです。

### Turn 002
Time: `00:00:57.174 - 00:01:03.400`
Speaker: `SPEAKER_01`
Text: 承知しました。失礼しました。
```

ポイント:

- IPA ZIP には `README.html`、`CONVERSION_INFO.md`、`ipa/<収録日時>.md` が入ります
- Readable Text ZIP には `README.html`、`CONVERSION_INFO.md`、`readable-text/<収録日時>.md` が入ります
- 成果物 markdown の `Source File` で元ファイル名を確認できます

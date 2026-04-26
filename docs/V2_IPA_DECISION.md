# V2 IPA Decision Memo

## 1. Primary backend candidates and comparison axes

- Candidate A: current `Sudachi + kana/ASCII heuristic`
  - strong on: no new runtime dependency, predictable fallback behavior, current repo fit
  - weak on: mixed-script Japanese, product names, proper nouns, backend name is larger than actual reading quality
- Candidate B: `pyopenjtalk.g2p(kana=True) + current kana->IPA`
  - strong on: Japanese-first local G2P, better fit for kanji-to-reading resolution, keeps local-first flow
  - weak on: new dependency risk if made default too early, user dictionary design is still undecided
- Candidate C: direct acoustic phoneme/forced-alignment path
  - strong on: can reduce transcript-derived reading errors in theory
  - weak on: implementation cost is too high for v2 first step, overlaps with ASR/alignment redesign

Comparison axes for v2:

- Japanese kanji reading stability
- mixed Japanese/Latin token behavior
- local LLM reconstruction compatibility
- dependency and packaging risk
- whether failures stay reviewable in markdown artifacts

## 2. Japanese weak points and diarization impact

- The largest Japanese weakness is not pure IPA rendering; it is wrong transcript text before IPA derivation.
- English product names, katakana loanwords, and kanji proper nouns are the main IPA failure cases.
- Diarization is affected mostly by ASR segmentation and timestamp quality, not by the IPA backend choice itself.
- Therefore IPA backend changes can improve artifact quality and reconstruction fallback quality, but they will not fix speaker boundary collapse on their own.

## 3. Tolerable vs intolerable error under local LLM reconstruction

Acceptable:

- small phone-level differences that keep the intended Japanese reading recoverable
- long-vowel or devoicing noise that does not change clause identity
- minor punctuation or spacing noise

Not acceptable:

- wrong proper noun reading
- dropped clause or merged neighboring clause
- heavy Latin-token collapse that changes the referenced product/person name
- speaker boundary mistakes that attach a sentence to the wrong speaker

## 4. Temporary composition and deferred options

Adopt now:

- keep current Sudachi path as production default
- add an experimental `pyopenjtalk` candidate behind a backend seam for comparison
- keep diarization and reconstruction wiring unchanged for the first validation step

Defer now:

- always-on `pyopenjtalk` dependency rollout
- direct audio-to-IPA backend
- diarization model swap
- full signature/settings/UI plumbing for backend selection

## 5. First repo implementation unit

The first implementation unit is not a pipeline-wide switch. It is:

1. make `worker/src/timeline_for_audio_worker/ipa_backend.py` accept a pluggable backend choice
2. keep current behavior as default
3. add an experimental `pyopenjtalk` path with safe fallback
4. verify the seam in unit tests before touching `processor`, `signature`, or UI

This keeps the v2 decision reversible while making the main backend question testable inside the repo.

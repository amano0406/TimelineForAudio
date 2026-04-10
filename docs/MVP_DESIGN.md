# TimelineForAudio MVP設計メモ

更新日: 2026-04-05 Asia/Tokyo

注記:

- この設計メモには旧検討案が残っています。
- 現行実装は `pass1 -> context builder -> pass2` の 2-pass ASR を採用しており、glossary ベースの transcript normalization は採用していません。
- 最新の実装契約は `README.md` と `docs/PIPELINE.md` を優先してください。

## 目的

`TimelineForAudio` は `TimelineForAudio` とは別リポジトリ・別アプリとして作る。

前提:

- local-first の desktop-style tool
- Docker Desktop 必須
- Hugging Face token 必須
- 不特定多数向けの導入簡略化より、手元での安定運用を優先
- UI / job / settings / ZIP / rerun / duplicate の思想は `TimelineForAudio` に寄せる
- pipeline は音声専用で再設計し、video 固有概念は持ち込まない

達成したい主出力:

- 音声ファイルから時系列の `timeline.md`
- `raw transcript`
- `TRANSCRIPTION_INFO.md`
- `speaker summary`
- `optional audio feature summary`
- ZIP
- failure 時は `FAILURE_REPORT.md` と `worker.log`

## 1. TimelineForAudio から継承する設計要素

継承対象は主に UI / job orchestration / export 契約で、根拠は既存実装:

- 2層構成
  - ASP.NET Core Razor Pages の `web`
  - Python の `worker`
  - worker 連携は HTTP ではなく shared filesystem
  - 参照: `/mnt/c/apps/TimelineForAudio/docs/APP_SPEC.md`, `/mnt/c/apps/TimelineForAudio/docker-compose.yml`
- canonical route は `/jobs/...`
  - `GET /jobs`
  - `GET /jobs/new`
  - `GET /jobs/{id}`
  - `GET /jobs/{id}/download`
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Pages/Jobs/Index.cshtml`, `/mnt/c/apps/TimelineForAudio/web/Pages/Jobs/New.cshtml`, `/mnt/c/apps/TimelineForAudio/web/Pages/Runs/Details.cshtml`
- job 契約
  - `request.json`
  - `status.json`
  - `result.json`
  - `manifest.json`
  - `RUN_INFO.md`
  - `TRANSCRIPTION_INFO.md`
  - `NOTICE.md`
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Services/RunStore.cs`
- upload-first UI
  - file 選択
  - folder 選択
  - chunked upload session
  - duplicate preview modal
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Pages/Jobs/New.cshtml`, `/mnt/c/apps/TimelineForAudio/web/Services/UploadSessionStore.cs`
- Jobs 一覧の思想
  - running job を先頭の特別枠で優先表示
  - 履歴一覧とは別に active panel を持つ
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Pages/Jobs/Index.cshtml`
- Job 詳細の思想
  - progress / elapsed / ETA
  - rerun with same settings
  - rerun with current settings
  - worker log tail
  - ZIP download
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Pages/Runs/Details.cshtml`
- modal ベースの確認 UI
  - `alert` 不使用
  - duplicate / delete / missing input などを modal で処理
- start / stop / Docker Desktop readiness check
  - `start.bat` で Docker Desktop を検査し、Compose 起動後に web readiness まで待つ
  - 参照: `/mnt/c/apps/TimelineForAudio/start.bat`
- model cache / token / settings の保存場所
  - `app-data/settings.json`
  - `app-data/secrets/huggingface.token`
  - cache volume
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Services/SettingsStore.cs`, `/mnt/c/apps/TimelineForAudio/docker-compose.yml`
- failure artifact の考え方
  - 成功した timeline は ZIP 可能
  - 一部失敗時は `FAILURE_REPORT.md` と `logs/worker.log` を同梱
  - 参照: `/mnt/c/apps/TimelineForAudio/web/Services/RunStore.cs`
- historical ETA の考え方
  - 過去 manifest の stage elapsed を使って予測する
  - 参照: `/mnt/c/apps/TimelineForAudio/worker/src/timeline_for_audio_worker/eta.py`

## 2. TimelineForAudio で捨てる概念

`TimelineForAudio` から切るべきもの:

- 画面抽出
  - screenshot sampling
  - screen diff
  - OCR
  - Florence caption
- video 固有 probe 項目
  - `video_codec`
  - `width`
  - `height`
  - `frame_rate`
  - `has_video`
- video timestamp を守るための silence trim + cut map 中心設計
  - `TimelineForAudio` では音声自体が主データなので、trim ではなく canonical audio normalization + VAD segmentation を主軸にする
- `media` という曖昧語の内部使用
  - 内部契約は `item` または `audio` に寄せる
  - `videos_total` などの命名は廃止し、`items_total` に置き換える
- screen note を timeline に差し込む構造
- video archive 向けの screen-heavy LLM export

## 3. TimelineForAudio で再設計する概念

### 3.1 Worker 契約

`TimelineForAudio` の `videos_total` 系は音声専用アプリでは不自然なので、契約を最初から汎化する。

推奨:

- `items_total`
- `items_done`
- `items_skipped`
- `items_failed`
- `current_item`
- `item_id`

`job` 用語は UI では維持する。

### 3.2 Duplicate 判定

`TimelineForAudio` は `sha256` 単独 catalog が中心だが、`TimelineForAudio` は最初から以下の 2 軸で持つ。

- `source_hash`
  - 元ファイル bytes の SHA-256
- `conversion_signature`
  - 同じ音声でも、設定・モデル・pipeline version が変われば別結果として扱うための署名

判定は 3 種類に分ける:

- exact reusable
  - `source_hash` 一致
  - `conversion_signature` 一致
  - completed artifact が存在
- same source, different conversion
  - `source_hash` 一致
  - `conversion_signature` 不一致
- new
  - どちらも一致なし

### 3.3 Setup readiness

`TimelineForAudio` では Hugging Face token を必須扱いにする。

MVP の開始条件:

- Docker worker が起動している
- Hugging Face token が保存済み
- `pyannote/speaker-diarization-community-1` へのアクセス確認が通る

これは `TimelineForAudio` より厳しくする。

## 4. MVP 範囲

MVP に入れる:

- file 選択
- directory 選択
- upload-first の job 作成 UI
- 音声文字起こし
- 話者分離
- timeline markdown 出力
- raw transcript 保存
- Jobs 一覧
- Job 詳細
- Settings
- duplicate 判定
- rerun with same settings
- rerun with current settings
- ZIP ダウンロード
- failure report
- elapsed / ETA の土台
- metadata 保存
- pause / silence summary
- loudness summary
- speaking rate summary
- pitch summary
- overlap / interruption summary
- speaker confidence summary
- optional voice feature summary

MVP で後回しにする:

- cross-job speaker linking
- speaker embedding の UI 露出
- voice print 的な比較機能
- 高度な prosody 推定
  - emotion
  - certainty
  - politeness
  - sarcasm
- LUFS ベースの厳密 broadcast loudness 校正
- per-language 特化の speaking rate
  - 日本語 mora/sec
  - 英語 syllable/sec
- NeMo diarization への切替 UI
- SaaS 配布や一般ユーザー向け導線

## 5. モデル・技術候補の整理

### 5.1 Transcription 候補

候補:

- `openai/whisper`
- `faster-whisper`
- wav2vec2 系 alignment layer

調査結果:

- `faster-whisper` は CTranslate2 ベースで、同 README では `openai/whisper` より同精度で最大 4 倍高速・省メモリとされ、`word_timestamps=True` と `vad_filter=True` を持つ
  - 出典: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- 明示的な alignment layer を足すと word-level timestamp の補正余地は増えるが、追加モデル管理と Docker 運用の複雑度も増える
- 現行の ASR 契約では、ASR と diarization を分離した方が `conversion_signature` と rerun 判定を素直に保てる

推奨判断:

- MVP の ASR コアは `faster-whisper`
- alignment layer は phase 2 の optional 追加要素として残す
- `openai/whisper` は reference/fallback に留め、既定実装にはしない

理由:

- `TimelineForAudio` は screen pipeline を持たないため、ASR と diarization を明示的に分離した方が契約設計しやすい
- `faster-whisper` 単体で word timestamps と VAD を使える
- `conversion_signature` に ASR backend / model / params を素直に入れやすい
- alignment model を常時必須にすると Docker 運用の複雑度が上がる

推奨モデル構成:

- `standard`
  - `faster-whisper medium`
  - CPU: `int8`
  - GPU: `float16`
- `high`
  - `faster-whisper large-v3`
  - GPU 優先
  - CPU high は非推奨だが実行は許可

phase 2:

- `high+aligned`
  - `faster-whisper large-v3`
  - alignment layer を追加

### 5.2 Diarization 候補

候補:

- `pyannote/speaker-diarization-community-1`
- NVIDIA NeMo diarization
- ASR-integrated diarization wrapper

調査結果:

- `community-1` は mono 16k 入力、downmix/resample 自動、speaker assignment/counting 改善、`exclusive speaker diarization`、offline use を持つ
  - 出典: [pyannote community-1 model card](https://huggingface.co/pyannote/speaker-diarization-community-1)
- `exclusive_speaker_diarization` は transcription timestamps との reconciliation を簡単にする
  - 出典: [pyannote community-1 model card](https://huggingface.co/pyannote/speaker-diarization-community-1)
- NeMo は end-to-end Sortformer 系と cascaded pipeline の両方を持ち、`vad_multilingual_marblenet`, `titanet_large`, `ecapa_tdnn`, `diar_msdd_telephonic` などの構成がある
  - 出典: [NVIDIA NeMo speaker diarization docs](https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/speaker_diarization/results.html)

推奨判断:

- MVP の diarization は `pyannote/speaker-diarization-community-1`
- NeMo は phase 2 の代替 backend 候補

理由:

- Hugging Face token 必須という前提と相性が良い
- `exclusive speaker diarization` が transcription merge に直接効く
- Docker Compose での運用面では pyannote の方が MVP の dependency surface が小さい
- NeMo は強いが、モデル群・設定群・後処理群まで含めると MVP の安定化コストが高い

### 5.3 VAD / silence segmentation 候補

候補:

- `Silero VAD`
- `faster-whisper` 内蔵 VAD filter
- `ffmpeg silencedetect`
- NeMo `vad_multilingual_marblenet`

調査結果:

- Silero VAD は `get_speech_timestamps` を提供し、8000/16000Hz をサポート、CPU でも軽く、ONNX も使える
  - 出典: [Silero VAD](https://github.com/snakers4/silero-vad)
- `faster-whisper` は Silero VAD を内蔵し、`vad_filter=True` で silence の長い区間を除外できる
  - 出典: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

推奨判断:

- primary VAD: `Silero VAD`
- ASR 側でも `vad_filter=True` を有効化
- `ffmpeg silencedetect` は fallback もしくは comparison 用で、primary にはしない

理由:

- amplitude ベースの silence 検出だけだと無音ではない non-speech を誤検知しやすい
- VAD summary と ASR skip 挙動を近いロジックに寄せられる
- `pause / silence summary` を speech-aware に作れる

### 5.4 Loudness / volume / pause / pitch / speaking rate

推奨手法:

- pause / silence
  - Silero VAD の speech timestamps から非発話区間を反転
  - summary:
    - total_silence_sec
    - silence_ratio
    - pause_count
    - median_pause_ms
    - long_pause_count
- loudness / volume
  - FFmpeg `volumedetect`
  - FFmpeg `astats`
  - `astats` は `RMS_peak`, `RMS_trough`, `Peak_level`, `Noise_floor`, `Zero_crossings` などを出せる
  - 出典: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)
- speaking rate
  - ASR word timestamps と transcript から計算
  - MVP は language-agnostic を優先し、
    - `tokens_per_min`
    - `chars_per_sec`
    - `speech_density`
    を主指標にする
  - 日本語専用の mora/sec は後回し
- pitch / tone
  - `librosa.pyin` を使って F0 を推定
  - summary:
    - voiced_ratio
    - median_f0_hz
    - p10 / p90
    - f0_iqr
  - 出典: [librosa.pyin](https://librosa.org/doc/latest/generated/librosa.pyin.html)
- timbre / voice color 近似
  - `librosa.feature.mfcc`
  - `librosa.feature.rms`
  - 追加で `spectral_centroid`, `spectral_bandwidth`, `spectral_flatness` を使う
  - 出典: [librosa.feature.mfcc](https://librosa.org/doc/latest/generated/librosa.feature.mfcc.html), [librosa.feature.rms](https://librosa.org/doc/latest/generated/librosa.feature.rms.html)

判断:

- loudness / pause / pitch / speaking rate は MVP に入れる
- timbre は optional metadata として入れる
- これらの抽出失敗は job 全体を落とさない

### 5.5 Speaker embedding / voice feature をどこまで扱うか

候補:

- SpeechBrain `spkrec-ecapa-voxceleb`
- NeMo `titanet_large` / `ecapa_tdnn`
- pyannote 付随情報のみ

調査結果:

- SpeechBrain の `spkrec-ecapa-voxceleb` は speaker verification と speaker embedding 抽出に使え、16kHz single-channel を前提にしている
  - 出典: [SpeechBrain ECAPA model card](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb)

推奨判断:

- MVP では raw embedding vector を主契約にしない
- ただし将来拡張用に interface は切っておく
- optional feature flag で SpeechBrain ECAPA を差し込める形にする

MVP でやること:

- `voice_feature_summary` は timbre/prosody 系の要約に留める
- `speaker_confidence_summary` は embedding 依存ではなく、diarization/transcript 整合性から作る

phase 2:

- per-speaker embedding centroid
- same-speaker consistency score
- cross-job speaker linking

## 6. 推奨モデル構成

MVP 推奨 stack:

- audio normalization
  - `ffmpeg` で canonical mono 16k WAV
- VAD
  - `Silero VAD`
- transcription
  - `faster-whisper`
  - `standard`: `medium`
  - `high`: `large-v3`
- diarization
  - `pyannote/speaker-diarization-community-1`
- speaker assignment
  - `exclusive_speaker_diarization` を優先
  - regular diarization は overlap 判定に使用
- acoustic features
  - loudness: `ffmpeg volumedetect` + `astats`
  - pitch: `librosa.pyin`
  - timbre: `librosa mfcc` + spectral features
- optional embeddings
  - phase 2 で `speechbrain/spkrec-ecapa-voxceleb`

この構成を推す理由:

- Docker Compose で固めやすい
- GPU / CPU の両方に自然に対応できる
- diarization を core feature として扱える
- `conversion_signature` に backend と params を明示的に持ち込める

## 7. metadata 設計

### 7.1 Job-level

`request.json`

- `schema_version`
- `job_id`
- `created_at`
- `output_root_id`
- `output_root_path`
- `profile`
- `requested_compute_mode`
- `processing_quality`
- `duplicate_policy`
- `conversion_signature`
- `conversion_signature_payload`
- `input_items`

`status.json`

- `job_id`
- `state`
- `current_stage`
- `message`
- `warnings`
- `items_total`
- `items_done`
- `items_skipped`
- `items_failed`
- `current_item`
- `current_item_elapsed_sec`
- `current_stage_elapsed_sec`
- `processed_duration_sec`
- `total_duration_sec`
- `estimated_remaining_sec`
- `progress_percent`
- `started_at`
- `updated_at`
- `completed_at`

`result.json`

- `job_id`
- `state`
- `run_dir`
- `processed_count`
- `skipped_count`
- `error_count`
- `timeline_index_path`
- `warnings`

### 7.2 Manifest item

各 item に保存したいもの:

- `input_id`
- `original_path`
- `file_name`
- `audio_id`
- `status`
- `duration_seconds`
- `size_bytes`
- `extension`
- `container_name`
- `audio_codec`
- `channels`
- `sample_rate`
- `bitrate_kbps`
- `source_hash`
- `normalized_audio_hash`
- `duplicate_status`
- `duplicate_match_kind`
- `duplicate_of_job_id`
- `duplicate_of_audio_id`
- `diarization_enabled`
- `requested_compute_mode`
- `effective_compute_mode`
- `compute_type`
- `processing_quality`
- `pipeline_version`
- `conversion_signature`
- `asr_backend`
- `asr_model_id`
- `asr_model_version`
- `diarization_backend`
- `diarization_model_id`
- `diarization_model_version`
- `vad_backend`
- `vad_model_id`
- `vad_model_version`
- `feature_pipeline_version`
- `processing_wall_seconds`
- `stage_elapsed_seconds`
- `transcript_language`
- `transcript_token_count`
- `transcript_char_count`
- `speaker_count`
- `pause_summary`
- `silence_summary`
- `loudness_summary`
- `speaking_rate_summary`
- `pitch_summary`
- `overlap_summary`
- `speaker_confidence_summary`
- `diarization_quality_summary`
- `voice_feature_summary`

### 7.3 Summary object の shape

`pause_summary`

- `pause_count`
- `median_pause_ms`
- `p90_pause_ms`
- `long_pause_count`
- `long_pause_threshold_ms`

`silence_summary`

- `total_silence_sec`
- `silence_ratio`
- `speech_sec`
- `speech_ratio`
- `detector`

`loudness_summary`

- `mean_volume_db`
- `max_volume_db`
- `rms_peak_db`
- `rms_trough_db`
- `noise_floor_db`

`speaking_rate_summary`

- `tokens_per_min`
- `chars_per_sec`
- `segments_per_min`
- `speech_density`

`pitch_summary`

- `voiced_ratio`
- `median_f0_hz`
- `p10_f0_hz`
- `p90_f0_hz`
- `f0_iqr_hz`

`overlap_summary`

- `overlap_sec`
- `overlap_ratio`
- `overlap_event_count`
- `interruption_event_count`

`speaker_confidence_summary`

- `method`
- `coverage_ratio`
- `boundary_conflict_ratio`
- `dominant_overlap_ratio`
- `confidence_label`

`diarization_quality_summary`

- `method`
- `speaker_count_stability`
- `short_turn_ratio`
- `overlap_consistency`
- `quality_label`

注意:

- `speaker_confidence_summary` と `diarization_quality_summary` は ground truth ではなく推定値
- これはモデル出力の直接 confidence ではなく、transcript と diarization の整合性から作る heuristic である

## 8. conversion signature 設計

### 8.1 目的

同じ `source_hash` でも、以下が変われば別変換として扱えるようにする:

- pipeline version
- model
- backend
- compute mode
- compute type
- processing quality
- VAD 設定
- diarization 設定
- feature extraction 設定
- timeline render 設定

### 8.2 推奨 payload

```json
{
  "schema_version": 1,
  "project": "TimelineForAudio",
  "pipeline_version": "0.1.0-mvp1",
  "profile": "quality-first",
  "input_normalization": {
    "target_channels": 1,
    "target_sample_rate": 16000,
    "target_format": "wav"
  },
  "transcription": {
    "backend": "faster-whisper",
    "model_id": "large-v3",
    "model_version": "pinned-or-resolved",
    "word_timestamps": true,
    "vad_filter": true,
    "beam_size": 5,
    "condition_on_previous_text": false
  },
  "alignment": {
    "enabled": false,
    "backend": null,
    "model_id": null,
    "model_version": null
  },
  "diarization": {
    "enabled": true,
    "backend": "pyannote",
    "model_id": "pyannote/speaker-diarization-community-1",
    "model_version": "pinned-or-resolved",
    "exclusive_assignment": true
  },
  "vad": {
    "backend": "silero-vad",
    "model_id": "silero-vad",
    "model_version": "pinned-or-resolved",
    "min_silence_duration_ms": 500
  },
  "features": {
    "loudness_backend": "ffmpeg-volumedetect-astats",
    "pitch_backend": "librosa-pyin",
    "voice_feature_backend": "librosa-mfcc",
    "speaker_embedding_backend": "disabled"
  },
  "render": {
    "timeline_schema": 1,
    "speaker_merge_gap_ms": 900,
    "include_overlap_notes": true
  },
  "runtime": {
    "requested_compute_mode": "gpu",
    "compute_type": "float16"
  }
}
```

### 8.3 署名の作り方

1. payload を sort key 付き canonical JSON にする
2. UTF-8 bytes に変換
3. SHA-256 を取る
4. hex lower を `conversion_signature` として保存

### 8.4 catalog の shape

`.timeline-for-audio/catalog.jsonl`

1 行に 1 completed artifact:

- `source_hash`
- `normalized_audio_hash`
- `conversion_signature`
- `job_id`
- `audio_id`
- `run_dir`
- `timeline_path`
- `raw_transcript_path`
- `speaker_summary_path`
- `audio_feature_summary_path`
- `pipeline_version`
- `created_at`

index は以下を構築する:

- `(source_hash, conversion_signature) -> latest completed row`
- `source_hash -> rows[]`
- `normalized_audio_hash -> rows[]` これは将来用

### 8.5 duplicate modal の分岐

- exact reusable がある
  - `既存結果を再利用`
  - `同じ設定で再処理`
- same source, different conversion がある
  - `既存結果を開く`
  - `現在の設定で再処理`

modal には差分理由を出す:

- processing quality changed
- asr model changed
- diarization backend changed
- pipeline version changed

## 9. 出力物とディレクトリ構造

job root:

```text
job-20260405-...
  request.json
  status.json
  result.json
  manifest.json
  RUN_INFO.md
  TRANSCRIPTION_INFO.md
  NOTICE.md
  logs/
    worker.log
  items/
    audio-...
      source.json
      audio/
        normalized.wav
        probe.json
        vad_segments.json
      transcript/
        raw.json
        raw.md
      diarization/
        regular_segments.json
        exclusive_segments.json
        overlap.json
        speaker_summary.md
      features/
        loudness.json
        pitch.json
        speaking_rate.json
        voice_features.json
        audio_feature_summary.md
      timeline/
        timeline.md
  llm/
    timeline_index.jsonl
```

ZIP:

```text
TimelineForAudio-export.zip
  README.md
  TRANSCRIPTION_INFO.md
  timelines/
    *.md
  raw_transcripts/
    *.md
    *.json
  speaker_summaries/
    *.md
  audio_feature_summaries/
    *.md
  FAILURE_REPORT.md
  logs/
    worker.log
```

## 10. timeline.md の shape

MVP の timeline は screen 情報を持たないので、音声中心にする。

```md
# Audio Timeline

- Source: `...`
- Audio ID: `...`
- Duration: `...`
- Speakers: `...`

## 00:00:12.340 - 00:00:18.220
Speaker:
SPEAKER_01

Speech:
...

Audio Notes:
- Loudness: medium
- Pitch: stable
- Speaking rate: fast
- Overlap: none

## 00:00:18.220 - 00:00:20.900
Silence / Pause:
- long pause
```

MVP では prose を過剰に増やさず、以下を重視する:

- speaker turn
- raw speech
- pause / silence
- overlap / interruption
- short audio note

## 11. speaker confidence / diarization quality の作り方

これは source ではなく設計上の推定ロジック。

`speaker_confidence_summary`:

- word 区間ごとに dominant speaker を割り当てる
- 以下で confidence を作る
  - dominant overlap ratio
  - speaker boundary 近接率
  - non-covered transcript ratio
  - rapid speaker flip 率

`diarization_quality_summary`:

- 以下を合成
  - 短すぎる turn の比率
  - overlap 区間の割合
  - transcript 単語との整合率
  - speaker count の異常変動

label:

- `high`
- `medium`
- `low`

明示:

- ground truth ではない
- review 用の operational confidence

## 12. 実装計画

### Phase 0: 新規 repo scaffold

- `TimelineForAudio` を直接流用せず、`TimelineForAudio` を新規作成
- ただし初期骨格は以下をベースに移植
  - Docker Compose
  - start / stop scripts
  - ASP.NET Razor shell
  - settings / jobs / job details / upload session
  - Python worker daemon

### Phase 1: generic contract への置換

- env var を `TIMELINE_FOR_AUDIO_*` に変更
- namespace / project 名 / compose service 名を変更
- `videos_*` -> `items_*`
- `current_media` -> `current_item`
- `media/` -> `items/`
- `.timeline-for-audio/` -> `.timeline-for-audio/`

### Phase 2: settings / duplicate / signature

- Settings に以下を追加・整理
  - Hugging Face token 必須
  - compute mode
  - processing quality
- conversion signature payload 実装
- catalog v2 実装
- duplicate preview API を source hash + conversion signature 対応に変更
- duplicate modal に exact / changed-settings 分岐を追加

### Phase 3: audio preflight

- ffprobe で audio metadata
- source hash
- canonical normalization
- normalized audio hash
- manifest 初期化

### Phase 4: audio pipeline

- Silero VAD
- faster-whisper transcription
- pyannote diarization
- speaker assignment merge
- pause / silence summary
- loudness summary
- pitch summary
- speaking rate summary
- overlap / interruption summary
- timeline render
- raw transcript / speaker summary / feature summary 出力

### Phase 5: export / rerun / failure

- ZIP export
- raw transcript / speaker summary / feature summary を ZIP 同梱
- `FAILURE_REPORT.md`
- rerun with same settings
- rerun with current settings

### Phase 6: ETA / history

- audio-specific historical ETA predictor
- item duration / codec / sample rate / channel count / diarization enabled を特徴量にする

### Phase 7: tests / smoke

- Python unit tests
  - signature canonicalization
  - duplicate matching
  - VAD summary
  - speaker merge
  - timeline rendering
- .NET / Playwright E2E
  - new job
  - duplicate modal
  - jobs list running panel
  - rerun
  - zip download
- `docker compose up --build`
- smoke with small sample wav/mp3

## 13. 実装開始時の推奨順

最短で MVP に入るならこの順:

1. `TimelineForAudio` web shell を複製して `TimelineForAudio` に rename
2. generic contract へ名称整理
3. upload / jobs / details / settings をまず動かす
4. worker の preflight と duplicate/signature を先に固める
5. その後に audio pipeline を実装する

理由:

- UI と orchestration を先に固めると、worker 側の試行錯誤を job 単位で回しやすい
- `conversion_signature` を後付けにすると duplicate と rerun の仕様が崩れる

## 14. 最終判断

現時点の推奨:

- `TimelineForAudio` は `TimelineForAudio` の UI / job / export 骨格を継承
- ASR は `faster-whisper` を主軸
- diarization は `pyannote community-1` を主軸
- VAD は `Silero VAD` を主軸
- feature は `ffmpeg` + `librosa`
- `conversion_signature` は MVP の最初から強く入れる
- `speaker confidence` と `diarization quality` は heuristic summary として出す
- `speaker embedding` は interface だけ用意し、MVP では主契約にしない

この方針なら、`TimelineForAudio` に似た UX を維持しつつ、音声専用アプリとして無理のない MVP に落とせる。

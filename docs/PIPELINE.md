# Pipeline

## 1. Request Creation

The CLI writes `request.json` into a new `job-*` directory under the selected output root.

The request contains:

- job id
- output root selection
- duplicate policy
- token-enabled flag
- fully expanded input items
- compute mode
- language hint
- job-level supplemental context text
- generation signature

## 2. Worker Pickup

The Python worker daemon scans enabled output roots for `job-*` directories whose `status.json` is still `pending`.

## 3. Preflight

For every input item:

- resolve the source path
- probe duration, codec, channels, sample rate, and file size with `ffprobe`
- compute SHA-256
- compute the generation signature
- check duplicate state against `.timeline-for-audio/catalog.jsonl`
- the duplicate key includes `source hash + generation signature + source file identity`
- source file identity is based on input root id and relative path, so a renamed file is treated as a different file

The worker writes `manifest.json` before heavy processing starts.

## 4. Audio Preparation

The worker normalizes each input into a stable analysis format:

1. decode the source audio with `ffmpeg`
2. write full mono `16kHz` timeline copy to `audio/source-normalized.wav`
3. scan the full copy for non-silent speech-candidate intervals
4. write the speech-candidate processing audio to `audio/normalized.wav`
5. write `audio/cut_map.json`
6. write timeline event artifacts under `analysis/`

`cut_map.json` maps timestamps from `audio/normalized.wav` back to the original audio-relative timeline.

## 5. Cleanup-Source Transcription

The worker calls `faster-whisper` to generate cleanup-oriented source text from the speech-candidate processing audio.

- language: derived from the CLI language setting when available
- device: `cpu` or `cuda`
- built-in VAD filtering
- no user-visible prompt injection at this stage

If GPU transcription fails, the worker can fall back to CPU and records a warning in the transcript metadata.

Artifacts written here:

- `transcript/cleanup_source.json`
- `transcript/cleanup_source.md`

## 6. Cleanup And Reconstruction Preparation

The worker prepares turn alignment and readable-text reconstruction input from:

- cleanup-source cues
- optional job-level supplemental context text
- normalized language hint

Artifacts written here can include:

- `transcript/context_primary.txt`
- `transcript/context_secondary.txt` when provided
- `transcript/context_merged.txt`
- `transcript/context_report.json`

## 7. Turn Alignment And Speaker Assignment

The worker produces turn-oriented source spans from the recording and aligns speakers when diarization is available.

Artifacts written here:

- `transcript/turns_source.json`
- `transcript/turns_source.md`
- `transcript/transcript_delta.json`

## 8. Diarization Enrichment

If `pyannote/speaker-diarization-community-1` is available and the Hugging Face prerequisites are satisfied, diarization runs on the full normalized timeline copy and aligns speaker turns to the current turn spans.

The worker preloads the normalized audio with `torchaudio`, passes waveform + sample rate into `pyannote`, keeps the current turn text fixed, and assigns speakers from diarization turns to turn timestamps for downstream IPA and readable-text generation.

If diarization is unavailable or fails:

- transcription still completes
- `diarization_used` stays false
- the error is recorded in transcript metadata

Artifacts written here:

- `transcript/turns_words.json`
- `transcript/turns_speaker_spans.json`
- `analysis/diarization_turns.json`

Speaker labels remain generic machine labels. The worker does not infer real names, identity, gender, age, or speaker attributes.

## 8.5 Timeline Events

The worker records the original audio timeline as candidate events:

- `speech_candidate`
- `silence_or_noise_candidate`

`silence_or_noise_candidate` means the interval was not selected for speech-focused processing. It is not a semantic classification of the sound.

Artifacts written here:

- `analysis/timeline_events.json`
- `analysis/Timeline Events.md`

## 9. IPA Generation

The worker derives IPA per turn and keeps speaker + timestamp + IPA aligned as the canonical intermediate.

Artifacts written here:

- `ipa/ipa_turns.json`
- `ipa/IPA.md`
- `review/review_data.json`
- `review/review.html`
- `review/process_data.json`
- `review/process.html`

`review.html` is a local inspection helper for checking IPA tokens against a selected local audio file. It does not embed the audio file. `process.html` is a local inspection helper that links the generated source, audio, cut-map, transcript, diarization, and IPA files in processing order.

## 10. Readable-Text Reconstruction

The worker reconstructs readable text from IPA turns, language hint, and optional supplemental context.

Artifacts written here:

- `readable-text/readable_text_turns.json`
- `readable-text/Readable Text.md`

## 11. Export Packaging

After the job finishes, the app can build one of two reduced review packages:

- `README.html`
- `CONVERSION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- either the IPA markdown output or the Readable Text markdown output

`README.html` is the human entrypoint for exported results.

## 12. Failure Model

- item-level failures do not abort the entire job when other items can still complete
- the worker logs stack traces to `logs/worker.log`
- `status.json` and `result.json` are updated even on failure
- failed or warning jobs can still export successful artifacts plus failure diagnostics

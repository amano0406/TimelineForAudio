# App Spec

## Goal

`TimelineForAudio` converts local audio files into IPA-first outputs that can be reviewed locally or handed to ChatGPT or another LLM.

The supported interface is the Python worker CLI running inside Docker. The previous ASP.NET Core web UI has been removed.

The system prioritizes:

- IPA as the canonical intermediate
- Docker-driven local processing
- readable job output for LLM workflows
- local processing over cloud dependencies
- preserving the original audio timeline
- per-turn timestamps and speaker alignment
- speech-candidate processing for long recordings
- generic speaker labels without identity inference

## App Model

- `worker`: Python CLI and worker daemon inside Docker
- `docker compose`: required worker container runtime for normal use
- `start.ps1` / `cli.ps1`: Windows PowerShell front door
- `start.bat` / `cli.bat` / `stop.bat` / `uninstall.bat`: Windows launchers for the matching PowerShell scripts
- `start.command` / `cli.command` / `stop.command` / `uninstall.command`: WSL/Unix backdoor wrappers
- `uninstall.ps1`: removes this project's Docker resources when the user intentionally uninstalls the app, then optionally removes saved app data, `settings.json`, and `.env`
- `.docker/docker-compose.paths.yml`: generated local Docker bind-mount override
- coordination: filesystem job directories
- runtime code path: Docker uses dependencies from the image and the CLI source mounted from `/workspace/worker/src`

## CLI Flow

1. start the Docker worker with `start.ps1`
2. run CLI commands through `cli.ps1`
3. save settings when needed
4. create local `settings.json` with `settings init` when missing
5. register stable input directories with `settings input-root` when the local defaults need changes
6. register the stable output directory with `settings output-root` when the local defaults need changes
7. run `refresh`
8. process only changed or new audio files
9. inspect job status and artifacts
10. archive either IPA or Readable Text output

## Input Model

The CLI supports:

- `settings input-root list/add/remove/enable/disable/clear`
- `settings output-root list/set`
- `settings init`
- `scan`
- `refresh`
- `refresh --source-id`
- `--language`
- `--ipa-backend`
- `--vad-profile`
- `--supplemental-context`
- `--supplemental-context-file`
- `--ipa-only`
- `evaluate --prediction --reference`

`jobs create --file` and `jobs create --directory` remain available for one-off work, but the primary product flow is `refresh` over configured input roots.

`evaluate` compares produced turn artifact JSON with a reference JSON. It can read a direct `--prediction` path or resolve an artifact from `--job-id`, `--media-id`, and `--artifact-kind`. It reports text CER, IPA error rate, speaker label accuracy, and a lightweight speaker time mismatch proxy for regression checks. The speaker time mismatch proxy is not a full DER implementation.

Supported audio extensions:

- `.mp3`
- `.wav`
- `.m4a`
- `.aac`
- `.flac`

## Output Model

Every job writes:

- `request.json`
- `status.json`
- `result.json`
- `manifest.json`
- `RUN_INFO.md`
- `CONVERSION_INFO.md`
- `NOTICE.md`
- `README.html` in the reduced export package

Each processed media item writes:

- `source.json`
- `audio/source-normalized.wav`
- `audio/normalized.wav`
- `audio/cut_map.json`
- `transcript/cleanup-source.json`
- `transcript/cleanup-source.md`
- `transcript/context_primary.txt`
- `transcript/context_secondary.txt` when provided
- `transcript/context_merged.txt`
- `transcript/context_report.json`
- `transcript/turns-source.json`
- `transcript/turns-source.md`
- `transcript/turns-source_words.json`
- `transcript/turns-source_speaker_spans.json`
- `transcript/transcript_delta.json`
- `analysis/diarization_turns.json`
- `analysis/timeline_events.json`
- `analysis/Timeline Events.md`
- `review/review.html`
- `review/review_data.json`
- `review/process.html`
- `review/process_data.json`
- `ipa/ipa_turns.json`
- `ipa/IPA.md`
- `readable-text/readable_text_turns.json` when readable text is enabled
- `readable-text/Readable Text.md` when readable text is enabled

Reduced export packaging writes:

- `README.html`
- `CONVERSION_INFO.md`
- `FAILURE_REPORT.md` when needed
- `logs/worker.log` when needed
- `ipa/*.md` for IPA export
- `readable-text/*.md` for Readable Text export

## Docker Path Mounts

Normal operation keeps Windows-style paths in `settings.json`, then maps them to Docker paths at launch time.

- `scripts/prepare-docker-paths.ps1` reads `settings.json`, or `settings.example.json` if local settings do not exist yet.
- enabled input roots are mounted read-only under `/host/input/<root-id>`
- enabled output roots are mounted writable under `/host/output/<root-id>`
- the generated Docker override sets `TIMELINE_FOR_AUDIO_PATH_MAPPINGS`
- worker path resolution uses that mapping before falling back to generic drive conversion
- `.docker/docker-compose.paths.yml` is generated local state and is not tracked by Git

## Settings

Stored in repository-local `settings.json`:

- input roots
- output roots
- audio extensions
- compute mode
- language hint
- IPA backend
- VAD profile
- Hugging Face terms confirmation

`settings.example.json` is tracked by Git. `settings.json` is local-only and ignored by Git.

Current default paths:

- input: `C:\TimelineData\Audio\`
- master output: `C:\TimelineData\AudioMaster\`

Stored separately under app data:

- Hugging Face token

Default app data root:

- Windows: `%LOCALAPPDATA%\TimelineForAudio`
- Unix-like environments: `~/.timeline-for-audio`

## CPU / GPU

- CPU path is the baseline
- GPU path uses the dedicated NVIDIA Docker worker overlay or local CUDA-capable Python setup
- model selection is internal and not exposed as a quality lane

## Duplicate Handling

- duplicate key: `source hash + generation signature + source file identity`
- source file identity: `<input-root-id>:<relative-path>`
- default `refresh` policy: skip unchanged files before creating processing work
- changing only the file name or relative path makes the item a different file
- stale catalog entries are processed again
- `--reprocess-duplicates` forces processing even when the duplicate key matches
- reuse / skip is automatic at the file level

The generation signature includes the requested IPA backend. Switching from `sudachi` to `pyopenjtalk` creates a different signature and prevents stale reuse.

The generation signature also includes the VAD profile and effective VAD parameters.

## IPA Backend

- default: `sudachi`
- experimental: `pyopenjtalk`

`pyopenjtalk` is for comparison runs. If it is requested but the worker cannot actually use it, the job fails instead of silently falling back, so A/B runs do not get contaminated.

## VAD Profile

- `default`: current-compatible `min_silence_duration_ms=500`
- `loose`: `min_silence_duration_ms=1000`
- `strict`: `min_silence_duration_ms=250`

The profile is written into `request.json`, transcript metadata, `source.json`, and `CONVERSION_INFO.md`.

## Diarization

- use `pyannote` only if token and terms confirmation are present
- otherwise continue without diarization
- diarization failures should not fail the whole job
- speaker labels stay generic, such as `SPEAKER_00`
- the app does not infer real names, identity, gender, age, or speaker attributes

## Timeline Preservation

- the original source file is never edited
- `audio/source-normalized.wav` is the full normalized processing copy
- `audio/normalized.wav` is the speech-candidate processing copy
- `audio/cut_map.json` maps speech-candidate audio timestamps back to the original timeline
- transcription and IPA turns are written with original audio-relative timestamps
- `analysis/timeline_events.json` records `speech_candidate` and `silence_or_noise_candidate` intervals
- `silence_or_noise_candidate` is a conservative candidate label, not a semantic sound classification

## Review Artifact

- `review/review.html` is a local inspection helper, not a primary user-facing export
- audio is not embedded in the review HTML
- the reviewer selects the matching local audio file in the browser
- the page synchronizes audio playback with IPA token rows from `review/review_data.json`
- source text is kept as a review aid, but IPA is the visible word-list value
- word-level sync falls back to segment-level rows when word timestamps are unavailable
- `review/process.html` is a local inspection helper for tracing which generated files were used at each processing stage
- `review/process.html` links to source metadata, normalized audio, cut map, transcript, diarization, and IPA artifacts

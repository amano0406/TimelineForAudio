# TimelineForAudio

TimelineForAudio is a local Docker-first CLI tool for turning configured audio directories into speaker-attributed acoustic-unit timelines.

The product does not reconstruct readable text, infer real speaker names, or summarize meaning. It prepares audio in a structured form that downstream tools can use.

## Current Pipeline

1. Read audio files from configured input directories.
2. Normalize each audio file for processing without modifying the original file.
3. Detect speech candidate ranges and keep original audio-relative timestamps.
4. Run required speaker diarization with `pyannote/speaker-diarization-community-1`.
5. Extract acoustic units with the current ZIPA 300M backend.
6. Write the primary JSON artifact.

Primary artifact:

```text
media/<media-id>/timeline/speaker-acoustic-units-timeline.json
```

Support artifacts:

```text
media/<media-id>/source/source-record.json
media/<media-id>/segments/speech-candidates.json
media/<media-id>/ai-raw/speaker-turns.raw.json
media/<media-id>/ai-raw/acoustic-units.raw.json
media/<media-id>/artifacts.json
```

## Settings

Persistent settings are stored in:

```text
C:\apps\TimelineForAudio\settings.json
```

`settings.example.json` is tracked by Git. `settings.json` is local-only and is not tracked.

Default shape:

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    {
      "id": "timeline-audio",
      "displayName": "Timeline Audio",
      "path": "C:\\TimelineData\\Audio\\",
      "enabled": true
    }
  ],
  "outputRoots": [
    {
      "id": "master",
      "displayName": "TimelineForAudio Master",
      "path": "C:\\TimelineData\\AudioMaster\\",
      "enabled": true
    }
  ],
  "audioExtensions": [".mp3", ".wav", ".m4a", ".aac", ".flac"],
  "huggingfaceTermsConfirmed": false,
  "computeMode": "cpu",
  "vadProfile": "default"
}
```

## Windows Entry Points

Use PowerShell from the project directory.

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings save --token <HUGGING_FACE_TOKEN> --terms-confirmed --compute-mode gpu
.\cli.ps1 refresh
.\cli.ps1 jobs list
.\cli.ps1 jobs show --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
.\cli.ps1 jobs archive --job-id job-YYYYMMDD-HHMMSS-xxxxxxxx
.\stop.ps1
```

Use `.\cli.ps1 refresh --reprocess-duplicates` only when you intentionally want to recompute unchanged files.

## Required External Setup

- Windows with Docker Desktop installed and running.
- Hugging Face token.
- Access approval for `pyannote/speaker-diarization-community-1`.
- Input directories mounted through the Docker startup scripts.

## Output Semantics

Speaker labels are mechanical labels such as `SPEAKER_00` and `SPEAKER_01`.

The timeline preserves:

- original source filename
- source hash
- audio-relative timestamps
- best-effort recorded datetime when available
- timezone metadata when known
- speaker label
- acoustic units

TimelineForAudio intentionally does not use language hints, supplemental text, or downstream LLM reconstruction.

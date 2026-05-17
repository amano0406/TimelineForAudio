# TimelineForAudio

TimelineForAudio is a local Docker-first product that converts local audio files into speaker/time/transcript timeline data.

The product integration surface is the small local HTTP API exposed by the worker container.

## Role

TimelineForAudio reads configured audio directories, detects changed audio files, and creates structured timeline artifacts for downstream Timeline products or LLM workflows.

It preserves source-audio-relative time, assigns mechanical speaker labels such as `SPEAKER_00`, and stores Whisper transcript text without rewriting it.

It does not create summaries, real speaker names, or identity guesses.

## Settings

Local settings live at:

```text
C:\apps\TimelineForAudio\settings.json
```

Current shape:

```json
{
  "schemaVersion": 1,
  "runtime": {
    "instanceName": "ff4e43e190",
    "apiPort": 19100
  },
  "inputRoots": [
    "C:\\apps\\Timeline\\data\\input\\audio"
  ],
  "outputRoot": "C:\\apps\\Timeline\\data\\to_text\\audio",
  "huggingFaceToken": "***REDACTED***",
  "computeMode": "gpu"
}
```

`huggingFaceToken` is the canonical token key. Older local files that still contain `huggingfaceToken` are read for compatibility and saved back using `huggingFaceToken`.

`runtime.instanceName` identifies this local Docker runtime. `runtime.apiPort` is used by the local API.

## Runtime

Run from Windows PowerShell:

```powershell
cd C:\apps\TimelineForAudio
.\start.ps1
```

`start.ps1` starts:

- Docker worker
- local API inside the worker container

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:19100/health
```

The response body is a JSON boolean:

```json
true
```

Operation API:

| Purpose | Route |
|---|---|
| Read settings | `POST /settings/status` |
| Save token / compute mode | `POST /settings/save` |
| List source audio | `POST /files/list` |
| List generated items | `POST /items/list` |
| Queue or run refresh | `POST /items/refresh` |
| Remove generated items | `POST /items/remove` |
| Create download ZIP | `POST /items/download` |
| Show model inventory | `POST /models/list` |

The API is served by the resident worker container. Starting the product is still
explicit; API routes do not start Docker implicitly.

## Output

Generated item output is written under `outputRoot`:

```text
<outputRoot>/
  <item-id>/
    convert_info.json
    timeline.json
```

`timeline.json` contains source metadata, speaker labels, time ranges, and transcript text.

`convert_info.json` contains source fingerprint, model/runtime metadata, processing-flow metadata, counts, and artifact names.

Download ZIPs contain:

```text
README.md
items/
  <item-id>/
    convert_info.json
    timeline.json
```

Source audio files are not included in master output or download ZIPs.

For concrete JSON structures and field meanings, see [docs/OUTPUTS.md](docs/OUTPUTS.md).

## Common Commands

| Purpose | Command |
|---|---|
| Start Docker worker and local API | `.\start.ps1` |
| Stop Docker worker and local API | `.\stop.ps1` |
| Check local API health | `Invoke-RestMethod http://127.0.0.1:19100/health` |
| Read settings through API | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/settings/status -Body '{}' -ContentType 'application/json'` |
| Save token / compute mode | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/settings/save -Body '{"token":"<HUGGING_FACE_TOKEN>","computeMode":"gpu"}' -ContentType 'application/json'` |
| List source audio | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/files/list -Body '{}' -ContentType 'application/json'` |
| Process changed files | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/refresh -Body '{}' -ContentType 'application/json'` |
| Process a small batch | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/refresh -Body '{"maxItems":3}' -ContentType 'application/json'` |
| List generated items | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/list -Body '{}' -ContentType 'application/json'` |
| Remove generated items dry-run | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/remove -Body '{"itemIds":["item-a","item-b"],"dryRun":true}' -ContentType 'application/json'` |
| Remove generated items | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/remove -Body '{"itemIds":["item-a","item-b"]}' -ContentType 'application/json'` |
| Create download ZIP | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/items/download -Body '{}' -ContentType 'application/json'` |
| Show model inventory | `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:19100/models/list -Body '{}' -ContentType 'application/json'` |
| Uninstall local containers | `.\uninstall.ps1` |

## Validation

Lightweight validation:

```powershell
.\scripts\lint.ps1
```

Operational validation with isolated generated data:

```powershell
.\scripts\lint.ps1 -IncludeOperationalSmoke
```

Real-model operational validation:

```powershell
.\scripts\test-operational.ps1 -UseRealModels
```

The operational tests use isolated settings, isolated Docker project names, and temporary input/output roots.

## Detailed Docs

| Document | When to read it |
|---|---|
| [docs/OUTPUTS.md](docs/OUTPUTS.md) | Reading master artifacts and download ZIPs |
| [docs/PIPELINE.md](docs/PIPELINE.md) | Understanding the processing pipeline |
| [docs/RUNTIME.md](docs/RUNTIME.md) | Docker, storage, model, GPU, token, and local-file boundaries |
| [docs/TESTING.md](docs/TESTING.md) | Running lightweight and operational checks |
| [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) | Reviewing dependency and model notices |

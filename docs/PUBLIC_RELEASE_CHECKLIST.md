# Public Release Checklist

Use this checklist before switching the repository from private to public.

## Repository Safety

- no real Hugging Face token is committed
- `.env`, `runs/`, `uploads/`, `app-data/`, and local caches are ignored
- sample timelines are redacted
- screenshots do not show local private data
- config samples use generic placeholder paths instead of personal paths
- generated ZIPs or run outputs are not tracked

## Build And Test

- `dotnet build web/TimelineForAudio.Web.csproj`
- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src`
- `scripts/test-e2e.ps1`
- at least one real local smoke run still completes
- ZIP download still works in the GUI

## Runtime Checks

- app starts from `start.bat` on Windows
- `start.command` still works as an experimental source-based path on macOS
- settings page loads without a token
- token save flow still works
- gated-model approval links still open the correct Hugging Face pages
- one uploaded file can complete end-to-end
- one completed run can be deleted

## Documentation

- README is accurate for the current startup flow
- Japanese README is still consistent with English README
- sample timeline files reflect the current output shape
- third-party notices and model/runtime notes match current dependencies
- the current `TimelineForAudio v0.x.y Tech Preview` wording is consistent where needed
- `Windows primary / macOS experimental` wording is consistent where needed
- `Docker Desktop required`, `first-run downloads`, and `GPU compose overlay` wording are consistent where needed
- speaker diarization is clearly described as optional and gated by token + approval

## Release Package

- `scripts/build-release-bundle.ps1 -Version 0.3.x` produces `TimelineForAudio-windows-local.zip`
- `SHA256SUMS.txt` is generated for the release bundle
- the bundle top folder is `TimelineForAudio-v0.x.y`
- the bundle does not include generated runs, uploads, app-data, tests, or local caches

## Before Making The Repo Public

- run `git grep` for personal local paths and names you do not want to publish
- confirm LICENSE and copyright text are what you want
- confirm no experimental or abandoned branches contain sensitive material
- review GitHub repository settings for issue tracking, discussions, and visibility

## Post-Publish Checks

- the GitHub Release title matches the newly published `TimelineForAudio v0.x.y Tech Preview`
- `releases/latest` resolves to the newly published tag
- `TimelineForAudio-windows-local.zip` downloads from the release page
- LP primary CTA can switch to `https://github.com/amano0406/TimelineForAudio/releases/latest`

# Public Release Checklist

Use this checklist before switching the repository from private to public.

## Repository Safety

- no real Hugging Face token is committed
- `.env`, `runs/`, `uploads/`, `app-data/`, `outputs/`, and local caches are ignored
- config samples use generic placeholder paths instead of personal paths
- generated ZIPs, artifacts, or job outputs are not tracked

## Build And Test

- `python -m unittest discover worker/tests` with `PYTHONPATH=worker/src`
- `scripts/lint.ps1` on Windows or `scripts/lint.sh` on Unix
- at least one real local smoke run still completes
- `jobs archive` produces the expected IPA and readable-text ZIP files

## Runtime Checks

- `start.bat` starts the worker container on Windows
- `start.command` starts the worker container on macOS or Linux
- `settings status` works without a token
- `settings save` can store language, compute mode, and Hugging Face token
- `jobs create` can create a job from one local audio file
- `jobs create --ipa-only` skips readable-text reconstruction
- `jobs archive` works for a completed job
- manual cleanup guidance is clear and does not require deleting original input audio

## Documentation

- README is accurate for the current startup flow
- Japanese README is still consistent with English README
- third-party notices and model/runtime notes match current dependencies
- the current `TimelineForAudio v0.x.y Tech Preview` wording is consistent where needed
- `Windows primary / macOS experimental` wording is consistent where needed
- `Docker Desktop required`, `first-run downloads`, and `GPU compose overlay` wording are consistent where needed
- speaker diarization is clearly described as optional and gated by token + approval
- all public docs describe CLI usage, not a web UI

## Release Package

- `scripts/build-release-bundle.ps1 -Version 0.3.x` produces `TimelineForAudio-windows-local.zip`
- `SHA256SUMS.txt` is generated for the release bundle
- the bundle top folder is `TimelineForAudio-v0.x.y`
- the bundle does not include generated runs, uploads, app-data, web assets, tests, screenshots, or local caches

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

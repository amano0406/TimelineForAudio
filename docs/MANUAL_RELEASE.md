# Manual Release Guide

This document defines the first public GitHub Release line for `TimelineForAudio`.

## Release Line

- current public line example: `TimelineForAudio v0.3.3 Tech Preview`
- tag format: `v0.x.y`
- first tag: `v0.3.0`
- initial support contract:
  - Windows primary
  - macOS experimental
  - Docker Desktop required
  - CPU baseline
  - GPU optional and best-effort

## Version Policy

- `v0.3.0` is the first public baseline
- patch releases use `v0.3.1`, `v0.3.2`, ...
- minor releases use `v0.4.0`, `v0.5.0`, ... when support contract, packaging, or user-visible flow changes materially
- `v1.0.0` is reserved for a later point where platform promise, release flow, and known limitations are more stable
- the canonical public version is the Git tag
- `worker/pyproject.toml` must match the release version before tagging

## Release Assets

Attach these files to the GitHub Release:

- `TimelineForAudio-windows-local.zip`
- `SHA256SUMS.txt`

Do not attach:

- Docker images
- model caches
- generated runs or uploads
- `app-data`
- tests
- private screenshots or reports

The Windows release bundle must contain a top folder named `TimelineForAudio-v0.x.y`.

## Manual Release Procedure

1. Confirm the release commit is on `main`.
2. Sync public-facing docs:
   - `README.md`
   - `README.ja.md`
   - `MODEL_AND_RUNTIME_NOTES.md`
   - `docs/PUBLIC_RELEASE_CHECKLIST.md`
   - `THIRD_PARTY_NOTICES.md`
3. Set the release version in `worker/pyproject.toml`.
4. Run the public release checks from `docs/PUBLIC_RELEASE_CHECKLIST.md`.
5. Build the Windows bundle:

   ```powershell
   .\scripts\build-release-bundle.ps1 -Version 0.3.3 -OutputDir .\release\v0.3.3
   ```

6. Verify these files exist:
   - `release\v0.3.3\TimelineForAudio-windows-local.zip`
   - `release\v0.3.3\SHA256SUMS.txt`
7. Create the annotated tag:

   ```powershell
   git tag -a v0.3.3 -m "TimelineForAudio v0.3.3"
   ```

8. Push `main` and the tag:

   ```powershell
   git push origin main
   git push origin v0.3.3
   ```

9. Create the GitHub Release manually:
   - repository: `https://github.com/amano0406/TimelineForAudio`
   - title: `TimelineForAudio v0.3.3 Tech Preview`
   - tag: `v0.3.3`
   - latest release: enabled
   - pre-release: disabled
10. Paste the release note template from `docs/RELEASE_NOTES_TEMPLATE.md`.
11. Attach:
   - `TimelineForAudio-windows-local.zip`
   - `SHA256SUMS.txt`
12. Publish the release.
13. After publish, verify:
   - `https://github.com/amano0406/TimelineForAudio/releases/latest`
   - `https://github.com/amano0406/TimelineForAudio/releases/latest/download/TimelineForAudio-windows-local.zip`

## LP URL Policy

- before the first release, the fallback URL is:
  - `https://github.com/amano0406/TimelineForAudio`
- after the first release, the LP primary CTA should use:
  - `https://github.com/amano0406/TimelineForAudio/releases/latest`
- the direct-download URL should be kept for future use, but not used as the initial LP primary CTA:
  - `https://github.com/amano0406/TimelineForAudio/releases/latest/download/TimelineForAudio-windows-local.zip`

The first LP CTA should send users to the release page, not directly to the asset, so they can read requirements and known limitations first.

## Future GitHub Actions Scope

Reasonable first automation scope:

- validate version/tag format
- run build and test steps
- build `TimelineForAudio-windows-local.zip`
- generate `SHA256SUMS.txt`
- create a draft GitHub Release

Keep these manual for the `v0.x` line:

- final publish
- final release note review
- final runtime caveat review

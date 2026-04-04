# Third-Party Notices

This repository includes or depends on third-party software. The list below is intended to make the main runtime and bundled components easy to review before sharing or publishing the project.

It is not a substitute for each dependency's original license text. If you redistribute binaries, Docker images, or bundled assets, review the upstream license terms again for the exact versions you ship.

## Application License

- `audio2timeline` application code: MIT

## Bundled Frontend Libraries

These files are vendored under `web/wwwroot/lib/`.

| Component | Version source | License |
| --- | --- | --- |
| Bootstrap | bundled in repo | MIT |
| jQuery | bundled in repo | MIT |
| jQuery Validation | bundled in repo | MIT |
| jQuery Validation Unobtrusive | bundled in repo | MIT |

## Direct Python Dependencies

These are the direct worker dependencies currently pinned in `worker/requirements-cpu.txt`.

| Package | Version | License |
| --- | --- | --- |
| ImageHash | 4.3.1 | BSD-2-Clause |
| Pillow | 11.1.0 | MIT-CMU |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| pytesseract | 0.3.13 | Apache-2.0 |
| easyocr | 1.7.2 | Apache-2.0 |
| transformers | 4.57.6 | Apache-2.0 |
| torch | 2.8.0 | BSD-3-Clause |
| torchaudio | 2.8.0 | BSD-style |
| torchvision | 0.23.0 | BSD-style |
| whisperx | 3.8.1 | BSD-2-Clause |

## Runtime Tools and Services

| Component | Role | License / Terms |
| --- | --- | --- |
| FFmpeg | media probing, extraction, screenshots | FFmpeg is LGPL-2.1-or-later by default, but some build configurations pull the whole binary under GPL. Verify the exact build you redistribute. |
| Tesseract OCR | OCR backend | Apache-2.0 |
| Hugging Face Hub | model download and gated access | service terms apply separately from code licenses |

## Model Weights and Gated Models

Model weights are not stored in this repository. They are downloaded on demand at runtime.

Important model-specific conditions currently used by the app:

| Model / Asset | Purpose | License / Access |
| --- | --- | --- |
| `pyannote/speaker-diarization-community-1` | optional speaker diarization | CC-BY-4.0, plus gated-access approval and Hugging Face token required |
| `florence-community/Florence-2-base` | screenshot captioning / image notes | MIT |

See [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md) for operational notes about model downloads, gated access, and first-run behavior.

## Notes for Redistribution

- The initial public release line ships a source-based Windows launcher bundle. It does not publish an official Docker image or native installer.
- The release bundle should contain launch scripts and source needed for local Docker builds, not generated runs, model caches, or private artifacts.
- If you publish Docker images, confirm the exact FFmpeg package and its license conditions for that image.
- If you upgrade pinned Python dependencies, review the resulting license set again.
- Transitive dependencies pulled by `pip` or `dotnet restore` are not exhaustively listed here.
- This project intentionally avoids `simple-diarizer` in the public v1 worker path to avoid pulling GPL-3.0 into the main application path.

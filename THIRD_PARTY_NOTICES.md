# Third-Party Notices

This repository includes or depends on third-party software. This file lists the main runtime dependencies that matter for local CLI and worker use.

It is not a substitute for each dependency's original license text. If you redistribute binaries, Docker images, or bundled assets, review the upstream license terms again for the exact versions you ship.

## Application License

- `TimelineForAudio` application code: MIT

## Direct Python Dependencies

These are the direct worker dependencies currently pinned in `worker/requirements-cpu.txt`.

| Package | Version | License |
| --- | --- | --- |
| `torch` | `2.8.0+cpu` | BSD-3-Clause |
| `torchaudio` | `2.8.0+cpu` | BSD-style |
| `pyannote.audio` | `4.0.1` | MIT |
| `onnxruntime` / `onnxruntime-gpu` | `1.23.2` | MIT |
| `lhotse` | `1.32.0` | Apache-2.0 |
| `huggingface_hub` | `0.36.0` | Apache-2.0 |
| `soundfile` | `0.13.1` | BSD-3-Clause |
| `python-dotenv` | `1.2.2` | BSD-3-Clause |

## Runtime Tools and Services

| Component | Role | License / Terms |
| --- | --- | --- |
| FFmpeg | media probing, decoding, and audio normalization | FFmpeg is LGPL-2.1-or-later by default, but some build configurations pull the whole binary under GPL. Verify the exact build you redistribute. |
| Hugging Face Hub | model download and gated access | service terms apply separately from code licenses |

## Model Weights and Gated Models

Model weights are not stored in this repository. They are downloaded on demand at runtime.

| Model / Asset | Purpose | License / Access |
| --- | --- | --- |
| `pyannote/speaker-diarization-community-1` | required speaker diarization | CC-BY-4.0, plus gated-access approval and Hugging Face token required |
| `anyspeech/zipa-large-crctc-300k` | acoustic-unit extraction | verify the upstream model card and license before redistribution |

See [MODEL_AND_RUNTIME_NOTES.md](MODEL_AND_RUNTIME_NOTES.md) for operational notes about model downloads, gated access, and first-run behavior.

## Notes for Redistribution

- The release bundle should contain launch scripts, Docker worker files, and Python worker source.
- Do not include generated runs, model caches, private artifacts, or tokens.
- If you publish Docker images, confirm the exact FFmpeg package and its license conditions for that image.
- If you upgrade pinned Python dependencies, review the resulting license set again.

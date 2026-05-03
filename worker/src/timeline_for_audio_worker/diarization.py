from __future__ import annotations

import os
import warnings
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from .runtime_profile import normalize_compute_mode
from .settings import load_huggingface_token

_DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
_TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD = "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"


def _iterate_diarization_rows(diarization_output: Any) -> list[dict[str, Any]]:
    annotation = getattr(diarization_output, "exclusive_speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = getattr(diarization_output, "speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = diarization_output

    rows: list[dict[str, Any]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        rows.append(
            {
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": str(speaker),
            }
        )
    return rows


@contextmanager
def _legacy_torch_checkpoint_load() -> Any:
    previous = os.environ.get(_TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD)
    os.environ[_TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD] = "1"
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Environment variable TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD detected.*",
                category=UserWarning,
            )
            yield
    finally:
        if previous is None:
            os.environ.pop(_TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD, None)
        else:
            os.environ[_TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD] = previous


def _load_diarization_audio_input(audio_path: Path) -> dict[str, Any]:
    try:
        import torchaudio
    except Exception as exc:
        raise RuntimeError(f"torchaudio is not available: {exc}") from exc

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if hasattr(waveform, "dim") and callable(getattr(waveform, "dim")) and waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    return {
        "waveform": waveform,
        "sample_rate": int(sample_rate),
    }


@lru_cache(maxsize=2)
def _load_diarizer(token: str, compute_mode: str) -> Any:
    try:
        from pyannote.audio import Pipeline
    except Exception as exc:
        raise RuntimeError(f"pyannote.audio is not available: {exc}") from exc

    with _legacy_torch_checkpoint_load():
        diarizer = Pipeline.from_pretrained(_DIARIZATION_MODEL_ID, token=token)
    if normalize_compute_mode(compute_mode) == "gpu":
        try:
            import torch

            if getattr(torch.cuda, "is_available", lambda: False)() and hasattr(diarizer, "to"):
                diarizer.to(torch.device("cuda"))
        except Exception:
            pass
    return diarizer


def generate_speaker_turns(
    *,
    source_name: str,
    audio_path: Path,
    compute_mode: str | None = None,
) -> dict[str, Any]:
    token = load_huggingface_token()
    diarization_rows: list[dict[str, Any]] = []
    error: str | None = None

    if not token:
        error = "Hugging Face token is not configured."
    else:
        try:
            diarizer = _load_diarizer(str(token), normalize_compute_mode(compute_mode))
            audio_input = _load_diarization_audio_input(audio_path)
            diarization_rows = _iterate_diarization_rows(diarizer(audio_input))
        except Exception as exc:
            error = str(exc)

    if error:
        raise RuntimeError(error)

    if not diarization_rows:
        warning = "Speaker diarization completed, but no speaker turns were found."
        return {
            "schema_version": 1,
            "source_name": source_name,
            "backend": "pyannote.audio",
            "model_id": _DIARIZATION_MODEL_ID,
            "status": "no_speaker_turns",
            "error": None,
            "warning_count": 1,
            "warnings": [warning],
            "turn_count": 0,
            "turns": [],
        }

    return {
        "schema_version": 1,
        "source_name": source_name,
        "backend": "pyannote.audio",
        "model_id": _DIARIZATION_MODEL_ID,
        "status": "ok",
        "error": None,
        "warning_count": 0,
        "warnings": [],
        "turn_count": len(diarization_rows),
        "turns": diarization_rows,
    }

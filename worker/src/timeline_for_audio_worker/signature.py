from __future__ import annotations

import hashlib
import json

from .acoustic_units import (
    ACOUSTIC_UNIT_BACKEND,
    ACOUSTIC_UNIT_MODEL_ID,
    ACOUSTIC_UNIT_TYPE,
)
from .runtime_profile import (
    normalize_compute_mode,
)
from .vad_profile import vad_config_for_profile

PIPELINE_VERSION = "2026-04-29-v3-speaker-acoustic-units1"
ACOUSTIC_UNIT_BACKEND_NAME = ACOUSTIC_UNIT_BACKEND
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
VAD_BACKEND = "ffmpeg-silencedetect"
VAD_MODEL_ID = "ffmpeg-silencedetect-noise-35db"
TIMELINE_SCHEMA = "speaker-acoustic-units-timeline-v1"


def resolve_acoustic_unit_model_id() -> str:
    return ACOUSTIC_UNIT_MODEL_ID


def build_conversion_signature(
    *,
    compute_mode: str | None,
    diarization_enabled: bool,
    vad_profile: str | None = None,
) -> str:
    return build_generation_signature(
        compute_mode=compute_mode,
        diarization_enabled=diarization_enabled,
        vad_profile=vad_profile,
    )


def build_generation_signature(
    *,
    compute_mode: str | None,
    diarization_enabled: bool,
    vad_profile: str | None = None,
) -> str:
    vad_config = vad_config_for_profile(vad_profile)
    payload = {
        "pipeline": "TimelineForAudio",
        "pipeline_version": PIPELINE_VERSION,
        "compute_mode": normalize_compute_mode(compute_mode),
        "acoustic_units": {
            "backend": ACOUSTIC_UNIT_BACKEND,
            "model_id": ACOUSTIC_UNIT_MODEL_ID,
            "unit_type": ACOUSTIC_UNIT_TYPE,
        },
        "diarization": {
            "required": True,
            "model_id": DIARIZATION_MODEL_ID,
            "requested_enabled_flag": bool(diarization_enabled),
        },
        "vad": {
            "backend": VAD_BACKEND,
            "model_id": VAD_MODEL_ID,
            "profile": vad_config["profile"],
            "filter": vad_config["vad_filter"],
            "parameters": vad_config["vad_parameters"],
        },
        "artifact": {
            "schema": TIMELINE_SCHEMA,
            "path": "timeline/speaker-acoustic-units-timeline.json",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

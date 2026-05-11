from __future__ import annotations

import hashlib
import json

from .runtime_profile import (
    normalize_compute_mode,
)
from .transcription import TRANSCRIPTION_BACKEND, TRANSCRIPTION_MODEL_ID
from .vad_profile import vad_config_for_profile

PIPELINE_VERSION = "2026-05-11-v1-whisper-transcript-timeline"
TRANSCRIPTION_BACKEND_NAME = TRANSCRIPTION_BACKEND
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
VAD_BACKEND = "ffmpeg-silencedetect"
VAD_MODEL_ID = "ffmpeg-silencedetect-noise-35db"
TIMELINE_SCHEMA = "timeline-v1"


def resolve_transcription_model_id() -> str:
    return TRANSCRIPTION_MODEL_ID


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
        "speech_transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "model_id": TRANSCRIPTION_MODEL_ID,
            "language": "auto",
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
            "path": "timeline.json",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

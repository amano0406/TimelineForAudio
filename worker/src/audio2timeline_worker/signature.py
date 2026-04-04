from __future__ import annotations

import hashlib
import json

PIPELINE_VERSION = "2026-04-05-mvp1"
TRANSCRIPTION_BACKEND = "faster-whisper"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
VAD_BACKEND = "silero-vad"
VAD_MODEL_ID = "faster-whisper-default"


def normalize_compute_mode(value: str | None) -> str:
    return "gpu" if str(value or "").strip().lower() == "gpu" else "cpu"


def normalize_processing_quality(value: str | None) -> str:
    return "high" if str(value or "").strip().lower() == "high" else "standard"


def resolve_transcription_model_id(processing_quality: str | None) -> str:
    return "large-v3" if normalize_processing_quality(processing_quality) == "high" else "medium"


def build_conversion_signature(
    *,
    compute_mode: str | None,
    processing_quality: str | None,
    diarization_enabled: bool,
) -> str:
    payload = {
        "pipeline": "audio2timeline",
        "pipeline_version": PIPELINE_VERSION,
        "compute_mode": normalize_compute_mode(compute_mode),
        "processing_quality": normalize_processing_quality(processing_quality),
        "transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "model_id": resolve_transcription_model_id(processing_quality),
            "language": "ja",
        },
        "diarization": {
            "enabled": diarization_enabled,
            "model_id": DIARIZATION_MODEL_ID if diarization_enabled else None,
        },
        "vad": {
            "backend": VAD_BACKEND,
            "model_id": VAD_MODEL_ID,
        },
        "features": {
            "pause": True,
            "loudness": True,
            "speaking_rate": True,
            "pitch": True,
            "voice_feature_summary": True,
        },
        "render": {
            "timeline_schema": "audio-markdown-v1",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

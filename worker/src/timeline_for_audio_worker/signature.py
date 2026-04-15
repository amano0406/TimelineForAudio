from __future__ import annotations

import hashlib
import json

from .runtime_profile import (
    TRANSCRIPTION_LANGUAGE,
    normalize_compute_mode,
    normalize_processing_quality,
    resolve_model_name_for_quality,
)

PIPELINE_VERSION = "2026-04-11-2pass2-diarize2"
TRANSCRIPTION_BACKEND = "faster-whisper"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
VAD_BACKEND = "faster-whisper-builtin"
VAD_MODEL_ID = "faster-whisper-default"
CONTEXT_BUILDER_VERSION = "context-builder-v1"


def resolve_transcription_model_id(processing_quality: str | None) -> str:
    return resolve_model_name_for_quality(processing_quality)


def _normalize_hint_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.strip() for line in normalized.split("\n")).strip()
    return normalized or None


def _hash_hint_text(value: str | None) -> str | None:
    normalized = _normalize_hint_text(value)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_conversion_signature(
    *,
    compute_mode: str | None,
    processing_quality: str | None,
    diarization_enabled: bool,
    supplemental_context_text: str | None = None,
    second_pass_enabled: bool = True,
    context_builder_version: str | None = None,
) -> str:
    payload = {
        "pipeline": "TimelineForAudio",
        "pipeline_version": PIPELINE_VERSION,
        "compute_mode": normalize_compute_mode(compute_mode),
        "processing_quality": normalize_processing_quality(processing_quality),
        "transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "model_id": resolve_transcription_model_id(processing_quality),
            "language": TRANSCRIPTION_LANGUAGE,
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
        "second_pass": {
            "enabled": bool(second_pass_enabled),
            "supplemental_context_sha256": _hash_hint_text(supplemental_context_text),
            "context_builder_version": context_builder_version or CONTEXT_BUILDER_VERSION,
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

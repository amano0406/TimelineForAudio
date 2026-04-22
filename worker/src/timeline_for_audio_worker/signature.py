from __future__ import annotations

import hashlib
import json

from .reconstruction import (
    build_reconstruction_decoding,
    resolve_reconstruction_backend,
    resolve_reconstruction_model_id,
    resolve_reconstruction_prompt_version,
)
from .runtime_profile import (
    TRANSCRIPTION_LANGUAGE,
    normalize_compute_mode,
    resolve_transcription_model_id as _resolve_transcription_model_id,
)

PIPELINE_VERSION = "2026-04-21-v2-ipa1"
TRANSCRIPTION_BACKEND = "faster-whisper"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
VAD_BACKEND = "faster-whisper-builtin"
VAD_MODEL_ID = "faster-whisper-default"
CONTEXT_BUILDER_VERSION = "context-builder-v1"
READABLE_TEXT_MARKDOWN_SCHEMA = "turn-markdown-v2"
IPA_BACKEND = "sudachi-reading-ipa-v1"
IPA_READING_BACKEND = "sudachipy-core"
IPA_ASCII_FALLBACK = "latin-heuristic-v1"
IPA_MARKDOWN_SCHEMA = "turn-markdown-v1"


def resolve_transcription_model_id() -> str:
    return _resolve_transcription_model_id()


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


def _normalize_language_hint(value: str | None) -> str | None:
    normalized = _normalize_hint_text(value)
    if not normalized:
        return None
    return normalized.lower()


def build_conversion_signature(
    *,
    compute_mode: str | None,
    diarization_enabled: bool,
    language_hint: str | None = None,
    supplemental_context_text: str | None = None,
    context_builder_version: str | None = None,
) -> str:
    return build_generation_signature(
        compute_mode=compute_mode,
        diarization_enabled=diarization_enabled,
        language_hint=language_hint,
        supplemental_context_text=supplemental_context_text,
        context_builder_version=context_builder_version,
    )


def build_generation_signature(
    *,
    compute_mode: str | None,
    diarization_enabled: bool,
    language_hint: str | None = None,
    supplemental_context_text: str | None = None,
    context_builder_version: str | None = None,
) -> str:
    payload = {
        "pipeline": "TimelineForAudio",
        "pipeline_version": PIPELINE_VERSION,
        "compute_mode": normalize_compute_mode(compute_mode),
        "transcription": {
            "backend": TRANSCRIPTION_BACKEND,
            "model_id": resolve_transcription_model_id(),
            "language": TRANSCRIPTION_LANGUAGE,
        },
        "reconstruction": {
            "backend": resolve_reconstruction_backend(language_hint, compute_mode),
            "model_id": resolve_reconstruction_model_id(language_hint, compute_mode),
            "prompt_version": resolve_reconstruction_prompt_version(language_hint, compute_mode),
            "decoding": build_reconstruction_decoding(language_hint, compute_mode),
            "language_hint": _normalize_language_hint(language_hint),
            "readable_text_schema": READABLE_TEXT_MARKDOWN_SCHEMA,
        },
        "ipa": {
            "backend": IPA_BACKEND,
            "reading_backend": IPA_READING_BACKEND,
            "ascii_fallback": IPA_ASCII_FALLBACK,
            "ipa_schema": IPA_MARKDOWN_SCHEMA,
        },
        "diarization": {
            "enabled": diarization_enabled,
            "model_id": DIARIZATION_MODEL_ID if diarization_enabled else None,
        },
        "vad": {
            "backend": VAD_BACKEND,
            "model_id": VAD_MODEL_ID,
        },
        "audio_features": {
            "pause": True,
            "loudness": True,
            "speaking_rate": True,
            "pitch": True,
            "voice_feature_summary": True,
        },
        "ipa_cleanup": {
            "supplemental_context_sha256": _hash_hint_text(supplemental_context_text),
            "rules_version": context_builder_version or CONTEXT_BUILDER_VERSION,
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

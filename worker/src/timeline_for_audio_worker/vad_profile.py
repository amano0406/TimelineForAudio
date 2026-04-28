from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_VAD_PROFILE = "default"

_VAD_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 500},
        "description": "Current-compatible faster-whisper VAD settings.",
    },
    "loose": {
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 1000},
        "description": "Keeps longer utterance runs together; useful when speech is split too aggressively.",
    },
    "strict": {
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 250},
        "description": "Splits on shorter pauses; useful for short turn-taking comparisons.",
    },
}


def resolve_vad_profile(value: str | None = None) -> str:
    normalized = str(value or DEFAULT_VAD_PROFILE).strip().lower()
    if normalized in _VAD_PROFILES:
        return normalized
    raise ValueError(f"Unsupported VAD profile: {value}")


def vad_config_for_profile(value: str | None = None) -> dict[str, Any]:
    profile = resolve_vad_profile(value)
    config = deepcopy(_VAD_PROFILES[profile])
    config["profile"] = profile
    return config

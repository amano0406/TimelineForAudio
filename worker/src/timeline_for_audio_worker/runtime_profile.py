from __future__ import annotations

from dataclasses import dataclass

HIGH_QUALITY_WARNING_GPU_MEMORY_GIB = 8.0
HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB = 10.0
TRANSCRIPTION_LANGUAGE = "ja"


@dataclass(frozen=True)
class RuntimeLane:
    lane_id: str
    compute_mode: str
    processing_quality: str
    model_id: str
    compute_types: tuple[str, ...]
    diarization_default_enabled: bool
    expert_only: bool
    recommended: bool


def normalize_compute_mode(value: str | None) -> str:
    return "gpu" if str(value or "").strip().lower() == "gpu" else "cpu"


def normalize_processing_quality(value: str | None) -> str:
    return "high" if str(value or "").strip().lower() == "high" else "standard"


def resolve_runtime_lane(compute_mode: str | None, processing_quality: str | None) -> RuntimeLane:
    normalized_compute_mode = normalize_compute_mode(compute_mode)
    normalized_processing_quality = normalize_processing_quality(processing_quality)
    lane_id = f"{normalized_compute_mode}-{normalized_processing_quality}"
    if normalized_compute_mode == "gpu":
        return RuntimeLane(
            lane_id=lane_id,
            compute_mode=normalized_compute_mode,
            processing_quality=normalized_processing_quality,
            model_id="large-v3" if normalized_processing_quality == "high" else "medium",
            compute_types=("float16", "int8_float16"),
            diarization_default_enabled=True,
            expert_only=False,
            recommended=normalized_processing_quality == "high",
        )
    return RuntimeLane(
        lane_id=lane_id,
        compute_mode=normalized_compute_mode,
        processing_quality=normalized_processing_quality,
        model_id="large-v3" if normalized_processing_quality == "high" else "medium",
        compute_types=("int8",),
        diarization_default_enabled=False,
        expert_only=normalized_processing_quality == "high",
        recommended=normalized_processing_quality == "standard",
    )


def resolve_model_name_for_quality(value: str | None) -> str:
    return resolve_runtime_lane("cpu", value).model_id


def resolve_diarization_default(compute_mode: str | None, *, token_ready: bool) -> bool:
    if not token_ready:
        return False
    return resolve_runtime_lane(compute_mode, "standard").diarization_default_enabled

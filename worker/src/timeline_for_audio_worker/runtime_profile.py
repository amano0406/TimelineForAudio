from __future__ import annotations

from dataclasses import dataclass

HIGH_QUALITY_WARNING_GPU_MEMORY_GIB = 8.0
HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB = 10.0


@dataclass(frozen=True)
class RuntimeLane:
    lane_id: str
    compute_mode: str
    model_id: str
    compute_types: tuple[str, ...]
    diarization_default_enabled: bool


def normalize_compute_mode(value: str | None) -> str:
    return "gpu" if str(value or "").strip().lower() == "gpu" else "cpu"


def resolve_runtime_lane(compute_mode: str | None) -> RuntimeLane:
    normalized_compute_mode = normalize_compute_mode(compute_mode)
    lane_id = normalized_compute_mode
    if normalized_compute_mode == "gpu":
        return RuntimeLane(
            lane_id=lane_id,
            compute_mode=normalized_compute_mode,
            model_id="medium",
            compute_types=("float16", "int8_float16"),
            diarization_default_enabled=True,
        )
    return RuntimeLane(
        lane_id=lane_id,
        compute_mode=normalized_compute_mode,
        model_id="medium",
        compute_types=("int8",),
        diarization_default_enabled=True,
    )


def resolve_diarization_default(compute_mode: str | None, *, token_ready: bool) -> bool:
    del compute_mode, token_ready
    return True

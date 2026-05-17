from __future__ import annotations

import os
from dataclasses import dataclass

HIGH_QUALITY_WARNING_GPU_MEMORY_GIB = 8.0
HIGH_QUALITY_RECOMMENDED_GPU_MEMORY_GIB = 10.0
WORKER_FLAVOR_ENV = "TIMELINE_FOR_AUDIO_WORKER_FLAVOR"


@dataclass(frozen=True)
class RuntimeLane:
    lane_id: str
    compute_mode: str
    model_id: str
    compute_types: tuple[str, ...]
    diarization_default_enabled: bool


def normalize_compute_mode(value: str | None) -> str:
    return "gpu" if str(value or "").strip().lower() == "gpu" else "cpu"


def current_worker_flavor() -> str:
    value = str(os.getenv(WORKER_FLAVOR_ENV) or "cpu").strip().lower()
    return "gpu" if value == "gpu" else "cpu"


def assert_runtime_supports_compute_mode(compute_mode: str | None) -> None:
    if normalize_compute_mode(compute_mode) != "gpu":
        return

    if current_worker_flavor() != "gpu":
        raise RuntimeError(
            "settings.json computeMode is gpu, but the running worker container is cpu. "
            "Restart the worker with start.ps1 so Docker can recreate "
            "the GPU worker."
        )

    try:
        import torch
    except Exception as exc:
        raise RuntimeError(f"GPU compute mode requires CUDA-enabled torch: {exc}") from exc

    if not getattr(torch.cuda, "is_available", lambda: False)():
        raise RuntimeError(
            "settings.json computeMode is gpu, but torch cannot access CUDA in this container."
        )


def resolve_runtime_lane(compute_mode: str | None) -> RuntimeLane:
    normalized_compute_mode = normalize_compute_mode(compute_mode)
    lane_id = normalized_compute_mode
    if normalized_compute_mode == "gpu":
        return RuntimeLane(
            lane_id=lane_id,
            compute_mode=normalized_compute_mode,
            model_id="large-v3",
            compute_types=("float16", "int8_float16"),
            diarization_default_enabled=True,
        )
    return RuntimeLane(
        lane_id=lane_id,
        compute_mode=normalized_compute_mode,
        model_id="large-v3",
        compute_types=("int8",),
        diarization_default_enabled=True,
    )


def resolve_diarization_default(compute_mode: str | None, *, token_ready: bool) -> bool:
    del compute_mode, token_ready
    return True

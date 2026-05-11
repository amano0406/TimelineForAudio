from __future__ import annotations

from .contracts import RunStatus

_ITEM_STAGE_BOUNDS: dict[str, tuple[float, float]] = {
    "extract_audio": (0.0, 0.18),
    "detect_speech_candidates": (0.18, 0.30),
    "diarize_audio": (0.30, 0.70),
    "transcribe_audio": (0.70, 0.94),
    "generate_artifacts": (0.96, 1.0),
}


def current_item_stage_fraction(
    stage_name: str, elapsed_sec: float, media_duration_sec: float, compute_mode: str
) -> float:
    lower, upper = _ITEM_STAGE_BOUNDS.get(stage_name, (0.0, 1.0))
    if upper <= lower:
        return upper
    expected = _stage_expected_seconds(stage_name, media_duration_sec, compute_mode)
    stage_progress = min(1.0, max(0.0, elapsed_sec / max(expected, 0.1)))
    return lower + ((upper - lower) * stage_progress)


def overall_progress_percent(
    *,
    processed_duration_sec: float,
    total_duration_sec: float,
    current_stage: str,
    current_stage_elapsed_sec: float,
    current_item_duration_sec: float,
    compute_mode: str,
    preflight_fraction: float = 1.0,
    total_items: int = 0,
    completed_items: int = 0,
) -> float:
    if current_stage == "queued":
        return 0.0
    if current_stage == "preflight":
        return round(5.0 * min(1.0, max(0.0, preflight_fraction)), 1)
    if current_stage == "llm_export":
        export_fraction = min(
            1.0,
            max(
                0.0,
                current_stage_elapsed_sec
                / _stage_expected_seconds("llm_export", 1.0, compute_mode),
            ),
        )
        return round(95.0 + (4.0 * export_fraction), 1)
    if current_stage == "completed":
        return 100.0
    if total_duration_sec > 0:
        current_item_fraction = current_item_stage_fraction(
            current_stage, current_stage_elapsed_sec, current_item_duration_sec, compute_mode
        )
        effective_processed = min(
            total_duration_sec,
            max(0.0, processed_duration_sec)
            + (max(0.0, current_item_duration_sec) * current_item_fraction),
        )
        duration_fraction = effective_processed / total_duration_sec
        return round(5.0 + (90.0 * duration_fraction), 1)

    if total_items <= 0:
        return 0.0

    current_item_fraction = current_item_stage_fraction(
        current_stage, current_stage_elapsed_sec, current_item_duration_sec, compute_mode
    )
    completed_fraction = min(1.0, max(0.0, (completed_items + current_item_fraction) / total_items))
    return round(5.0 + (90.0 * completed_fraction), 1)


def completed_progress_percent(
    *,
    processed_duration_sec: float,
    total_duration_sec: float,
    total_items: int,
    completed_items: int,
) -> float:
    if total_duration_sec > 0:
        completed_fraction = min(1.0, max(0.0, processed_duration_sec / total_duration_sec))
        return round(5.0 + (90.0 * completed_fraction), 1)

    if total_items <= 0:
        return 0.0

    completed_fraction = min(1.0, max(0.0, completed_items / total_items))
    return round(5.0 + (90.0 * completed_fraction), 1)


def completed_item_count(status: RunStatus) -> int:
    return status.items_done + status.items_skipped + status.items_failed


def _stage_expected_seconds(stage_name: str, media_duration_sec: float, compute_mode: str) -> float:
    safe_duration = max(1.0, media_duration_sec)
    if stage_name == "extract_audio":
        return max(1.5, min(25.0, safe_duration * 0.06))
    if stage_name == "detect_speech_candidates":
        return max(1.0, min(30.0, safe_duration * 0.08))
    if stage_name == "diarize_audio":
        factor = 0.10 if compute_mode == "gpu" else 0.45
        ceiling = 120.0 if compute_mode == "gpu" else 480.0
        return max(2.0, min(ceiling, safe_duration * factor))
    if stage_name == "transcribe_audio":
        factor = 0.18 if compute_mode == "gpu" else 0.90
        ceiling = 180.0 if compute_mode == "gpu" else 720.0
        return max(4.0, min(ceiling, safe_duration * factor))
    if stage_name == "generate_artifacts":
        return max(1.0, min(15.0, safe_duration * 0.03))
    if stage_name == "llm_export":
        return 5.0
    if stage_name == "preflight":
        return max(1.0, min(10.0, safe_duration * 0.02))
    return 5.0

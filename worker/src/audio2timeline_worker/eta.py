from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .contracts import ManifestItem

_TERMINAL_ITEM_STATES = {"completed", "failed", "skipped_duplicate"}
_MAX_MATCH_SCORE = 9.0
_STAGE_ORDER = [
    "extract_audio",
    "transcribe",
    "normalize_transcript",
    "analyze_audio",
    "timeline_render",
]
_DEFAULT_STAGE_SHARES = {
    "extract_audio": 0.16,
    "transcribe": 0.56,
    "normalize_transcript": 0.08,
    "analyze_audio": 0.14,
    "timeline_render": 0.06,
}


def _normalize_text(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _bitrate_bucket(bitrate: int | None) -> str:
    value = int(bitrate or 0)
    if value <= 0:
        return "unknown"
    if value <= 96_000:
        return "low"
    if value <= 192_000:
        return "standard"
    if value <= 320_000:
        return "high"
    return "lossless"


def _sample_rate_bucket(sample_rate: int | None) -> str:
    value = int(sample_rate or 0)
    if value <= 0:
        return "unknown"
    if value <= 16_000:
        return "narrowband"
    if value <= 24_000:
        return "voice"
    if value <= 48_000:
        return "standard"
    return "high"


def _scale_sample_total(sample_duration_sec: float, sample_total_sec: float, target_duration_sec: float) -> float:
    safe_sample_duration = max(1.0, sample_duration_sec)
    safe_target_duration = max(1.0, target_duration_sec)
    duration_ratio = max(0.25, min(4.0, safe_target_duration / safe_sample_duration))
    fixed_overhead = min(12.0, sample_total_sec * 0.35)
    variable_component = max(0.0, sample_total_sec - fixed_overhead) * duration_ratio
    return max(1.0, round(fixed_overhead + variable_component, 3))


@dataclass(frozen=True)
class EtaPrediction:
    total_seconds: float
    confidence: float
    sample_count: int
    stage_seconds: dict[str, float]


@dataclass(frozen=True)
class HistoricalSample:
    compute_mode: str
    processing_quality: str
    container_name: str | None
    audio_codec: str | None
    channel_count: int | None
    sample_rate_bucket: str
    bitrate_bucket: str
    duration_seconds: float
    processing_wall_seconds: float
    stage_elapsed_seconds: dict[str, float]


class EtaPredictor:
    def __init__(self, samples: Iterable[HistoricalSample], compute_mode: str, processing_quality: str) -> None:
        self._samples = list(samples)
        self._compute_mode = _normalize_text(compute_mode) or "cpu"
        self._processing_quality = _normalize_text(processing_quality) or "standard"

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def predict_item(self, item: ManifestItem) -> EtaPrediction | None:
        candidates = [
            sample
            for sample in self._samples
            if sample.compute_mode == self._compute_mode
            and sample.processing_quality == self._processing_quality
        ]
        if not candidates:
            return None

        item_container = _normalize_text(item.container_name)
        item_audio_codec = _normalize_text(item.audio_codec)
        item_channel_count = item.audio_channels
        item_sample_rate_bucket = _sample_rate_bucket(item.audio_sample_rate)
        item_bitrate_bucket = _bitrate_bucket(item.bitrate)

        scored: list[tuple[float, HistoricalSample]] = []
        for sample in candidates:
            score = 1.0
            if item_audio_codec and sample.audio_codec == item_audio_codec:
                score += 3.0
            if item_container and sample.container_name == item_container:
                score += 1.0
            if item_channel_count and sample.channel_count == item_channel_count:
                score += 2.0
            if sample.sample_rate_bucket == item_sample_rate_bucket:
                score += 1.5
            if sample.bitrate_bucket == item_bitrate_bucket:
                score += 1.5
            scored.append((score, sample))

        scored.sort(key=lambda row: row[0], reverse=True)
        top_matches = scored[: min(12, len(scored))]
        total_weight = sum(score for score, _ in top_matches)
        weighted_prediction = sum(
            score
            * _scale_sample_total(
                sample.duration_seconds,
                sample.processing_wall_seconds,
                item.duration_seconds,
            )
            for score, sample in top_matches
        ) / max(total_weight, 0.1)
        average_score = total_weight / max(len(top_matches), 1)
        sample_factor = min(1.0, len(top_matches) / 5.0)
        feature_factor = min(1.0, average_score / _MAX_MATCH_SCORE)
        confidence = min(0.9, 0.15 + (0.55 * sample_factor) + (0.30 * feature_factor))
        stage_shares = _weighted_stage_shares(top_matches)
        stage_seconds = {
            stage_name: round(weighted_prediction * share, 3)
            for stage_name, share in stage_shares.items()
        }
        return EtaPrediction(
            total_seconds=max(1.0, round(weighted_prediction, 3)),
            confidence=round(confidence, 3),
            sample_count=len(top_matches),
            stage_seconds=stage_seconds,
        )


def build_eta_predictor(
    *,
    output_root: Path,
    current_job_id: str,
    compute_mode: str,
    processing_quality: str,
) -> EtaPredictor:
    samples: list[HistoricalSample] = []
    normalized_compute_mode = _normalize_text(compute_mode) or "cpu"
    normalized_processing_quality = _normalize_text(processing_quality) or "standard"
    if not output_root.exists():
        return EtaPredictor(samples, normalized_compute_mode, normalized_processing_quality)

    job_dirs = sorted(output_root.glob("job-*")) + sorted(output_root.glob("run-*"))
    seen_dirs: set[Path] = set()
    for run_dir in job_dirs:
        resolved = run_dir.resolve()
        if resolved in seen_dirs or resolved.name == current_job_id or not resolved.is_dir():
            continue
        seen_dirs.add(resolved)

        request_path = resolved / "request.json"
        manifest_path = resolved / "manifest.json"
        if not request_path.exists() or not manifest_path.exists():
            continue

        try:
            request = json.loads(request_path.read_text(encoding="utf-8-sig", errors="replace"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue

        if (_normalize_text(request.get("compute_mode")) or "cpu") != normalized_compute_mode:
            continue
        if (_normalize_text(request.get("processing_quality")) or "standard") != normalized_processing_quality:
            continue

        for item in manifest.get("items", []):
            if str(item.get("status") or "").lower() != "completed":
                continue
            processing_wall_seconds = float(item.get("processing_wall_seconds") or 0.0)
            duration_seconds = float(item.get("duration_seconds") or 0.0)
            if processing_wall_seconds <= 0 or duration_seconds <= 0:
                continue

            samples.append(
                HistoricalSample(
                    compute_mode=normalized_compute_mode,
                    processing_quality=normalized_processing_quality,
                    container_name=_normalize_text(item.get("container_name")),
                    audio_codec=_normalize_text(item.get("audio_codec")),
                    channel_count=_to_optional_int(item.get("audio_channels")),
                    sample_rate_bucket=_sample_rate_bucket(_to_optional_int(item.get("audio_sample_rate"))),
                    bitrate_bucket=_bitrate_bucket(_to_optional_int(item.get("bitrate"))),
                    duration_seconds=duration_seconds,
                    processing_wall_seconds=processing_wall_seconds,
                    stage_elapsed_seconds=_normalize_stage_elapsed(item.get("stage_elapsed_seconds")),
                )
            )

    return EtaPredictor(samples, normalized_compute_mode, normalized_processing_quality)


def estimate_remaining_seconds(
    *,
    predictor: EtaPredictor,
    manifest_items: list[ManifestItem],
    legacy_remaining_sec: float | None,
    current_item_index: int | None = None,
    current_item_elapsed_sec: float = 0.0,
    current_stage_name: str | None = None,
    current_stage_elapsed_sec: float = 0.0,
    include_export_stage: bool = True,
) -> float | None:
    history_remaining = 0.0
    confidences: list[float] = []
    predicted_any = False

    if current_item_index is not None and 0 <= current_item_index < len(manifest_items):
        current_item = manifest_items[current_item_index]
        if str(current_item.status).lower() not in _TERMINAL_ITEM_STATES and current_item.duplicate_status != "duplicate_skip":
            prediction = predictor.predict_item(current_item)
            if prediction is not None:
                if current_stage_name:
                    history_remaining += _remaining_for_current_stage(
                        prediction.stage_seconds,
                        current_stage_name,
                        current_stage_elapsed_sec,
                    )
                else:
                    history_remaining += max(
                        0.0,
                        prediction.total_seconds - max(0.0, current_item_elapsed_sec),
                    )
                confidences.append(prediction.confidence)
                predicted_any = True

    for index, item in enumerate(manifest_items):
        if current_item_index is not None and index <= current_item_index:
            continue
        if item.duplicate_status == "duplicate_skip" or str(item.status).lower() in _TERMINAL_ITEM_STATES:
            continue
        prediction = predictor.predict_item(item)
        if prediction is None:
            continue
        history_remaining += prediction.total_seconds
        confidences.append(prediction.confidence)
        predicted_any = True

    if predicted_any and include_export_stage:
        history_remaining += 5.0
        confidences.append(0.4)

    if not predicted_any:
        return legacy_remaining_sec

    history_confidence = sum(confidences) / max(len(confidences), 1)
    history_remaining = round(max(0.0, history_remaining), 3)
    if legacy_remaining_sec is None:
        return history_remaining

    blended = (history_remaining * history_confidence) + (legacy_remaining_sec * (1.0 - history_confidence))
    return round(max(0.0, blended), 3)


def _to_optional_int(value: object) -> int | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_optional_float(value: object) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_stage_elapsed(payload: object) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, float] = {}
    for stage_name in _STAGE_ORDER:
        value = _to_optional_float(payload.get(stage_name))
        if value is not None and value >= 0:
            normalized[stage_name] = value
    return normalized


def _weighted_stage_shares(top_matches: list[tuple[float, HistoricalSample]]) -> dict[str, float]:
    weighted_shares = {stage_name: 0.0 for stage_name in _STAGE_ORDER}
    total_weight = sum(score for score, _ in top_matches)
    if total_weight <= 0:
        return dict(_DEFAULT_STAGE_SHARES)

    for score, sample in top_matches:
        stage_elapsed = sample.stage_elapsed_seconds
        total_elapsed = sum(max(0.0, value) for value in stage_elapsed.values())
        if total_elapsed <= 0:
            for stage_name, share in _DEFAULT_STAGE_SHARES.items():
                weighted_shares[stage_name] += score * share
            continue
        for stage_name in _STAGE_ORDER:
            weighted_shares[stage_name] += score * (
                max(0.0, stage_elapsed.get(stage_name, 0.0)) / total_elapsed
            )

    normalized_total = sum(weighted_shares.values())
    if normalized_total <= 0:
        return dict(_DEFAULT_STAGE_SHARES)
    return {
        stage_name: weighted_shares[stage_name] / normalized_total
        for stage_name in _STAGE_ORDER
    }


def _remaining_for_current_stage(
    stage_seconds: dict[str, float],
    current_stage_name: str,
    current_stage_elapsed_sec: float,
) -> float:
    remaining = 0.0
    stage_found = False
    for stage_name in _STAGE_ORDER:
        target = max(0.0, stage_seconds.get(stage_name, 0.0))
        if stage_name == current_stage_name:
            stage_found = True
            remaining += max(0.0, target - max(0.0, current_stage_elapsed_sec))
            continue
        if stage_found:
            remaining += target
    if stage_found:
        return round(remaining, 3)
    total = sum(max(0.0, value) for value in stage_seconds.values())
    return round(max(0.0, total - max(0.0, current_stage_elapsed_sec)), 3)

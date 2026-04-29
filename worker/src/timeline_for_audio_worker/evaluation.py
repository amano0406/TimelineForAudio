from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_SPACE_RE = re.compile(r"\s+")
EVALUATION_SCHEMA_VERSION = 1

_ARTIFACT_JSON_PATHS = {
    "timeline": Path("timeline") / "speaker-acoustic-units-timeline.json",
    "speaker-acoustic-units-timeline": Path("timeline") / "speaker-acoustic-units-timeline.json",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def normalize_evaluation_artifact_kind(value: str | None) -> str:
    normalized = str(value or "timeline").strip().lower().replace("_", "-")
    if normalized in {"speaker-acoustic-units", "speaker-acoustic-units-timeline"}:
        return "speaker-acoustic-units-timeline"
    if normalized in _ARTIFACT_JSON_PATHS:
        return normalized
    raise ValueError(f"Unsupported evaluation artifact kind: {value}")


def resolve_job_prediction_path(
    *,
    run_dir: Path,
    media_id: str | None,
    artifact_kind: str,
) -> Path:
    media_root = run_dir / "media"
    if not media_root.exists():
        raise ValueError(f"Run does not contain a media directory: {run_dir}")

    if media_id:
        media_dir = media_root / media_id
        if not media_dir.exists() or not media_dir.is_dir():
            raise ValueError(f"Media item not found: {media_id}")
    else:
        candidates = sorted(path for path in media_root.iterdir() if path.is_dir())
        if len(candidates) != 1:
            raise ValueError(
                "Media id is required when a run contains zero or multiple media items."
            )
        media_dir = candidates[0]

    normalized_kind = normalize_evaluation_artifact_kind(artifact_kind)
    prediction_path = media_dir / _ARTIFACT_JSON_PATHS[normalized_kind]
    if not prediction_path.exists():
        raise ValueError(f"Prediction artifact JSON was not found: {prediction_path}")
    return prediction_path


def _turn_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []

    for key in (
        "turns",
        "speaker_segments",
        "segments",
        "diarization_turns",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _normalize_text(value: Any) -> str:
    return _SPACE_RE.sub("", str(value or "").strip())


def _normalize_acoustic_units(value: Any) -> str:
    text = str(value or "").strip().strip("/")
    return _SPACE_RE.sub(" ", text).strip()


def _row_text(row: dict[str, Any]) -> str:
    return str(row.get("text") or "")


def _row_acoustic_units(row: dict[str, Any]) -> str:
    return str(
        row.get("acoustic_units")
        or row.get("units")
        or ""
    )


def _row_speaker(row: dict[str, Any]) -> str:
    return str(row.get("speaker") or row.get("speaker_id") or "")


def _row_start(row: dict[str, Any]) -> float:
    return float(row.get("start_sec", row.get("original_start", row.get("start", 0.0))) or 0.0)


def _row_end(row: dict[str, Any]) -> float:
    return float(
        row.get("end_sec", row.get("original_end", row.get("end", row.get("start", 0.0))))
        or 0.0
    )


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _error_rate(predicted: str, reference: str) -> float | None:
    if not reference:
        return None
    return _edit_distance(predicted, reference) / len(reference)


def _speaker_label_accuracy(
    prediction_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> float | None:
    paired = list(zip(prediction_rows, reference_rows))
    labeled = [
        (prediction, reference)
        for prediction, reference in paired
        if _row_speaker(prediction) and _row_speaker(reference)
    ]
    if not labeled:
        return None
    matches = sum(
        1
        for prediction, reference in labeled
        if _row_speaker(prediction) == _row_speaker(reference)
    )
    return matches / len(labeled)


def _speaker_at(rows: list[dict[str, Any]], midpoint: float) -> str:
    for row in rows:
        start = _row_start(row)
        end = _row_end(row)
        if start <= midpoint <= end:
            return _row_speaker(row)
    return ""


def _speaker_time_mismatch_rate(
    prediction_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> float | None:
    total_duration = 0.0
    mismatch_duration = 0.0

    for reference in reference_rows:
        reference_speaker = _row_speaker(reference)
        start = _row_start(reference)
        end = _row_end(reference)
        duration = max(0.0, end - start)
        if duration <= 0.0 or not reference_speaker:
            continue
        total_duration += duration
        midpoint = start + duration / 2.0
        if _speaker_at(prediction_rows, midpoint) != reference_speaker:
            mismatch_duration += duration

    if total_duration <= 0.0:
        return None
    return mismatch_duration / total_duration


def evaluate_turn_artifacts(prediction_path: Path, reference_path: Path) -> dict[str, Any]:
    prediction_rows = _turn_rows(_read_json(prediction_path))
    reference_rows = _turn_rows(_read_json(reference_path))

    predicted_text = _normalize_text("".join(_row_text(row) for row in prediction_rows))
    reference_text = _normalize_text("".join(_row_text(row) for row in reference_rows))
    predicted_units = _normalize_acoustic_units(
        " ".join(_row_acoustic_units(row) for row in prediction_rows)
    )
    reference_units = _normalize_acoustic_units(
        " ".join(_row_acoustic_units(row) for row in reference_rows)
    )

    text_cer = _error_rate(predicted_text, reference_text)
    acoustic_unit_error_rate = _error_rate(predicted_units, reference_units)

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "prediction_path": str(prediction_path),
        "reference_path": str(reference_path),
        "prediction_turns": len(prediction_rows),
        "reference_turns": len(reference_rows),
        "text": {
            "cer": text_cer,
            "edit_distance": _edit_distance(predicted_text, reference_text)
            if reference_text
            else None,
            "reference_length": len(reference_text),
        },
        "acoustic_units": {
            "error_rate": acoustic_unit_error_rate,
            "edit_distance": _edit_distance(predicted_units, reference_units)
            if reference_units
            else None,
            "reference_length": len(reference_units),
        },
        "speaker": {
            "label_accuracy": _speaker_label_accuracy(prediction_rows, reference_rows),
            "time_mismatch_rate": _speaker_time_mismatch_rate(
                prediction_rows,
                reference_rows,
            ),
            "note": "time_mismatch_rate is a lightweight turn-level proxy, not full DER.",
        },
    }


def _format_metric(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_evaluation_markdown(payload: dict[str, Any]) -> str:
    text_metrics = payload.get("text", {})
    acoustic_unit_metrics = payload.get("acoustic_units", {})
    speaker_metrics = payload.get("speaker", {})
    lines = [
        "# Evaluation",
        "",
        f"- Prediction: `{payload.get('prediction_path')}`",
        f"- Reference: `{payload.get('reference_path')}`",
        f"- Prediction Turns: `{payload.get('prediction_turns')}`",
        f"- Reference Turns: `{payload.get('reference_turns')}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Text CER | `{_format_metric(text_metrics.get('cer'))}` |",
        f"| Acoustic Unit Error Rate | `{_format_metric(acoustic_unit_metrics.get('error_rate'))}` |",
        f"| Speaker Label Accuracy | `{_format_metric(speaker_metrics.get('label_accuracy'))}` |",
        f"| Speaker Time Mismatch Proxy | `{_format_metric(speaker_metrics.get('time_mismatch_rate'))}` |",
        "",
        "## Notes",
        "",
        "- Speaker time mismatch is a lightweight turn-level proxy, not full DER.",
        "- Missing reference text or acoustic units returns `N/A` for that metric.",
        "",
    ]
    return "\n".join(lines)


def write_evaluation_report(payload: dict[str, Any], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation.json"
    markdown_path = output_dir / "EVALUATION.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_evaluation_markdown(payload), encoding="utf-8")
    return {
        "evaluation_json_path": str(json_path),
        "evaluation_markdown_path": str(markdown_path),
    }

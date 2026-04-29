from __future__ import annotations

from pathlib import Path
from typing import Any

from .fs_utils import now_iso, write_json_atomic, write_text


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _bounded_float(value: Any, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return lower
    return min(upper, max(lower, parsed))


def _source_file_label(source_info: dict[str, Any]) -> str:
    for key in ("display_name", "original_path", "audio_id"):
        text = str(source_info.get(key) or "").strip()
        if not text:
            continue
        stem = Path(text.replace("\\", "/")).stem
        if stem:
            return stem
    return "audio"


def _normalize_speech_intervals(
    *,
    duration_seconds: float,
    cut_map: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for row in cut_map:
        start = _bounded_float(row.get("original_start"), 0.0, duration_seconds)
        end = _bounded_float(row.get("original_end"), start, duration_seconds)
        if end - start < 0.001:
            continue
        intervals.append((start, end))

    intervals.sort(key=lambda item: (item[0], item[1]))
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 0.001:
            merged.append((start, end))
            continue
        prev_start, prev_end = merged[-1]
        merged[-1] = (prev_start, max(prev_end, end))
    return merged


def build_timeline_events(
    *,
    source_name: str,
    duration_seconds: float,
    cut_map: list[dict[str, Any]],
) -> dict[str, Any]:
    duration = max(0.0, float(duration_seconds or 0.0))
    speech_intervals = _normalize_speech_intervals(
        duration_seconds=duration,
        cut_map=cut_map,
    )
    events: list[dict[str, Any]] = []
    cursor = 0.0

    def add_event(event_type: str, start: float, end: float, confidence: float) -> None:
        if end - start < 0.001:
            return
        events.append(
            {
                "index": len(events) + 1,
                "event_type": event_type,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration_seconds": round(max(0.0, end - start), 3),
                "confidence": round(confidence, 3),
                "time_label": f"{_timestamp_label(start)} - {_timestamp_label(end)}",
            }
        )

    for start, end in speech_intervals:
        if start > cursor:
            add_event("silence_or_noise_candidate", cursor, start, 0.5)
        add_event("speech_candidate", start, end, 0.6)
        cursor = max(cursor, end)

    if duration > cursor:
        add_event("silence_or_noise_candidate", cursor, duration, 0.5)

    return {
        "schema_version": 1,
        "source_name": source_name,
        "generated_at": now_iso(),
        "duration_seconds": round(duration, 3),
        "classification_source": "ffmpeg.silencedetect",
        "note": (
            "Speech candidates are derived from non-silent intervals with padding. "
            "Silence/noise candidates are the remaining timeline gaps and are not "
            "semantic sound classifications."
        ),
        "speech_candidate_count": sum(
            1 for event in events if event["event_type"] == "speech_candidate"
        ),
        "silence_or_noise_candidate_count": sum(
            1 for event in events if event["event_type"] == "silence_or_noise_candidate"
        ),
        "events": events,
    }


def render_timeline_events(
    *,
    output_path: Path,
    source_info: dict[str, Any],
    timeline_payload: dict[str, Any],
) -> str:
    source_label = _source_file_label(source_info)
    events = timeline_payload.get("events") or []
    lines = [
        "# Timeline Events",
        "",
        f"- File: `{source_label}`",
        f"- Duration: `{_timestamp_label(float(timeline_payload.get('duration_seconds') or 0.0))}`",
        f"- Classification Source: `{timeline_payload.get('classification_source') or 'unknown'}`",
        f"- Note: {timeline_payload.get('note') or ''}",
        "",
    ]
    if not events:
        lines.append("_No timeline events generated._")
        rendered = "\n".join(lines).rstrip() + "\n"
        write_text(output_path, rendered)
        return rendered

    for index, event in enumerate(events, start=1):
        event_type = str(event.get("event_type") or "unknown")
        lines.extend(
            [
                f"## Event {index:03d}",
                f"Time: `{event.get('time_label') or ''}`",
                f"Type: `{event_type}`",
                f"Confidence: `{event.get('confidence')}`",
                "",
            ]
        )

    rendered = "\n".join(lines).rstrip() + "\n"
    write_text(output_path, rendered)
    return rendered


def write_timeline_events(
    *,
    source_info: dict[str, Any],
    source_name: str,
    duration_seconds: float,
    cut_map: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    payload = build_timeline_events(
        source_name=source_name,
        duration_seconds=duration_seconds,
        cut_map=cut_map,
    )
    write_json_atomic(output_dir / "timeline_events.json", payload)
    render_timeline_events(
        output_path=output_dir / "Timeline Events.md",
        source_info=source_info,
        timeline_payload=payload,
    )
    return payload

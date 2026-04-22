from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _segment_text(segment: dict[str, Any] | None) -> str:
    if not segment:
        return ""
    return " ".join(str(segment.get("text") or "").split())


def _segment_speaker(segment: dict[str, Any] | None) -> str:
    if not segment:
        return ""
    return str(segment.get("speaker") or "SPEAKER_00")


def _segment_start(segment: dict[str, Any] | None) -> float:
    if not segment:
        return 0.0
    return float(
        segment.get("original_start", segment.get("start", segment.get("trimmed_start", 0.0))) or 0.0
    )


def write_transcript_delta(
    *,
    transcript_dir: Path,
    cleanup_source_payload: dict[str, Any],
    turns_source_payload: dict[str, Any],
) -> dict[str, Any]:
    cleanup_segments = (
        cleanup_source_payload.get("raw_segments")
        or cleanup_source_payload.get("segments", [])
        or []
    )
    turns_segments = (
        turns_source_payload.get("raw_segments")
        or turns_source_payload.get("segments", [])
        or []
    )
    max_len = max(len(cleanup_segments), len(turns_segments))
    changes: list[dict[str, Any]] = []

    for index in range(max_len):
        left = cleanup_segments[index] if index < len(cleanup_segments) else None
        right = turns_segments[index] if index < len(turns_segments) else None
        if left == right:
            continue
        changes.append(
            {
                "index": index,
                "cleanup_start": _segment_start(left) if left else None,
                "turns_start": _segment_start(right) if right else None,
                "cleanup_speaker": _segment_speaker(left) if left else None,
                "turns_speaker": _segment_speaker(right) if right else None,
                "cleanup_text": _segment_text(left) if left else None,
                "turns_text": _segment_text(right) if right else None,
            }
        )

    payload = {
        "cleanup_source_name": str(
            cleanup_source_payload.get("transcript_label") or "cleanup_source"
        ),
        "turns_source_name": str(turns_source_payload.get("transcript_label") or "turns_source"),
        "cleanup_segment_count": len(cleanup_segments),
        "turns_segment_count": len(turns_segments),
        "changed_segment_count": len(changes),
        "changes": changes,
    }
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "transcript_delta.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload

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


def write_pass_diff(
    *,
    transcript_dir: Path,
    pass1_payload: dict[str, Any],
    pass2_payload: dict[str, Any],
) -> dict[str, Any]:
    pass1_segments = pass1_payload.get("raw_segments") or pass1_payload.get("segments", []) or []
    pass2_segments = pass2_payload.get("raw_segments") or pass2_payload.get("segments", []) or []
    max_len = max(len(pass1_segments), len(pass2_segments))
    changes: list[dict[str, Any]] = []

    for index in range(max_len):
        left = pass1_segments[index] if index < len(pass1_segments) else None
        right = pass2_segments[index] if index < len(pass2_segments) else None
        if left == right:
            continue
        changes.append(
            {
                "index": index,
                "pass1_start": _segment_start(left) if left else None,
                "pass2_start": _segment_start(right) if right else None,
                "pass1_speaker": _segment_speaker(left) if left else None,
                "pass2_speaker": _segment_speaker(right) if right else None,
                "pass1_text": _segment_text(left) if left else None,
                "pass2_text": _segment_text(right) if right else None,
            }
        )

    payload = {
        "pass1_name": str(pass1_payload.get("pass_name") or "pass1"),
        "pass2_name": str(pass2_payload.get("pass_name") or "pass2"),
        "pass1_segment_count": len(pass1_segments),
        "pass2_segment_count": len(pass2_segments),
        "changed_segment_count": len(changes),
        "changes": changes,
    }
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "pass_diff.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload

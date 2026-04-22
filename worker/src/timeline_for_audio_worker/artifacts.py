from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .fs_utils import write_json_atomic, write_text

_DATETIME_PATTERNS = (
    "%Y-%m-%d %H-%M-%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y%m%d-%H%M%S",
    "%Y%m%d%H%M%S",
)


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_best_effort_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        parsed = None

    if parsed is not None:
        return parsed

    for pattern in _DATETIME_PATTERNS:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _source_file_label(source_info: dict[str, Any]) -> str:
    candidates = [
        source_info.get("recorded_at"),
        source_info.get("captured_at"),
        source_info.get("display_name"),
        source_info.get("original_path"),
        source_info.get("audio_id"),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        parsed = _parse_best_effort_datetime(text)
        if parsed is not None:
            return parsed.strftime("%Y-%m-%d %H-%M-%S")
        stem = Path(text).stem.strip()
        if stem:
            return stem
    return "audio"


def _language_hint(source_info: dict[str, Any], transcript_payload: dict[str, Any]) -> str:
    return (
        str(source_info.get("language_hint") or "").strip()
        or str(transcript_payload.get("language") or "").strip()
        or "und"
    )


def _speaker_count(turns: list[dict[str, Any]]) -> int:
    speakers = {
        str(turn.get("speaker") or "").strip()
        for turn in turns
        if str(turn.get("speaker") or "").strip()
    }
    return len(speakers)


def render_readable_text(
    *,
    output_path: Path,
    source_info: dict[str, Any],
    turns: list[dict[str, Any]],
    warnings: list[str] | None = None,
    speaker_count: int | None = None,
    speaker_count_status: str | None = None,
    speaker_count_note: str | None = None,
) -> str:
    lines = [
        "# Readable Text",
        "",
        f"- File: `{_source_file_label(source_info)}`",
        f"- Speakers: `{speaker_count if speaker_count is not None else _speaker_count(turns)}`",
        f"- Language Hint: `{str(source_info.get('language_hint') or 'und').strip() or 'und'}`",
        "",
    ]

    if not turns:
        lines.append("_No readable text turns generated._")
        rendered = "\n".join(lines).rstrip() + "\n"
        write_text(output_path, rendered)
        return rendered

    for index, turn in enumerate(turns, start=1):
        start = float(turn.get("start", 0.0) or 0.0)
        end = float(turn.get("end", start) or start)
        speaker = str(turn.get("speaker") or "SPEAKER_00")
        text = _compact_text(turn.get("text"))
        lines.extend(
            [
                f"### Turn {index:03d}",
                f"Time: `{_timestamp_label(start)} - {_timestamp_label(end)}`",
                f"Speaker: `{speaker}`",
                f"Text: {text}",
                "",
            ]
        )

    rendered = "\n".join(lines).rstrip() + "\n"
    write_text(output_path, rendered)
    return rendered


def render_ipa(
    *,
    output_path: Path,
    source_info: dict[str, Any],
    turns: list[dict[str, Any]],
    backend_name: str,
    status: str,
    warnings: list[str] | None = None,
    speaker_count: int | None = None,
    speaker_count_status: str | None = None,
    speaker_count_note: str | None = None,
) -> str:
    lines = [
        "# IPA",
        "",
        f"- File: `{_source_file_label(source_info)}`",
        f"- Speakers: `{speaker_count if speaker_count is not None else _speaker_count(turns)}`",
        f"- Language Hint: `{str(source_info.get('language_hint') or 'und').strip() or 'und'}`",
        "",
    ]

    if not turns:
        lines.append("_No IPA turns generated._")
        rendered = "\n".join(lines).rstrip() + "\n"
        write_text(output_path, rendered)
        return rendered

    for index, turn in enumerate(turns, start=1):
        start = float(turn.get("start", 0.0) or 0.0)
        end = float(turn.get("end", start) or start)
        speaker = str(turn.get("speaker") or "SPEAKER_00")
        ipa = str(turn.get("ipa") or "").strip()
        lines.extend(
            [
                f"## Turn {index:03d}",
                f"Time: `{_timestamp_label(start)} - {_timestamp_label(end)}`",
                f"Speaker: `{speaker}`",
                f"IPA: `{ipa}`",
                "",
            ]
        )

    rendered = "\n".join(lines).rstrip() + "\n"
    write_text(output_path, rendered)
    return rendered


def register_artifact(
    *,
    media_dir: Path,
    kind: str,
    title: str,
    display_name: str,
    role: str,
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None

    return {
        "kind": kind,
        "title": title,
        "display_name": display_name,
        "role": role,
        "format": path.suffix.lstrip(".").lower() or "text",
        "relative_path": path.relative_to(media_dir).as_posix(),
    }


def write_media_artifacts_index(
    *,
    media_dir: Path,
    media_id: str,
    primary_artifact_kind: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "media_id": media_id,
        "primary_artifact_kind": primary_artifact_kind,
        "artifacts": artifacts,
    }
    write_json_atomic(media_dir / "artifacts.json", payload)
    return payload

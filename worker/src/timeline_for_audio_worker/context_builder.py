from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from .fs_utils import write_text

CONTEXT_BUILDER_VERSION = "context-builder-v1"
DEFAULT_MAX_MERGED_LENGTH = 1600

_LATIN_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}")
_CJK_TERM_RE = re.compile(r"[一-龯ぁ-んァ-ヴー]{2,}")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_multiline_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n")).strip()
    return normalized


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _segment_bounds(segment: dict[str, Any]) -> tuple[float, float]:
    start = float(
        segment.get("original_start", segment.get("start", segment.get("trimmed_start", 0.0))) or 0.0
    )
    end = float(
        segment.get("original_end", segment.get("end", segment.get("trimmed_end", start))) or start
    )
    return start, max(start, end)


def _segment_cue_lines(segments: list[dict[str, Any]], limit: int = 8) -> list[str]:
    populated = [segment for segment in segments if _normalize_text(segment.get("text"))]
    if not populated:
        return []

    if len(populated) <= limit:
        selected = populated
    else:
        step = max(1, len(populated) // limit)
        selected = populated[::step][:limit]
        if selected[-1] is not populated[-1]:
            selected[-1] = populated[-1]

    rows: list[str] = ["chronological cues"]
    for segment in selected:
        start, _ = _segment_bounds(segment)
        speaker = _normalize_text(segment.get("speaker")) or "SPEAKER_00"
        text = _normalize_text(segment.get("text"))
        snippet = text[:96].rstrip()
        rows.append(f"{_timestamp_label(start)} {speaker} {snippet}")
    return rows


def _extract_terms(segments: list[dict[str, Any]], limit: int = 18) -> list[str]:
    counter: Counter[str] = Counter()
    for segment in segments:
        text = _normalize_text(segment.get("text"))
        if not text:
            continue
        for term in _LATIN_TERM_RE.findall(text):
            counter[term] += 1
        for term in _CJK_TERM_RE.findall(text):
            counter[term] += 1

    ranked = sorted(counter.items(), key=lambda row: (-row[1], -len(row[0]), row[0].lower()))
    return [term for term, _ in ranked[:limit]]


def _extract_identifiers(segments: list[dict[str, Any]], limit: int = 12) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for segment in segments:
        text = _normalize_text(segment.get("text"))
        if not text:
            continue
        for term in _LATIN_TERM_RE.findall(text):
            has_digit = any(char.isdigit() for char in term)
            has_upper = any(char.isupper() for char in term)
            if not (has_digit or has_upper or "-" in term or "_" in term):
                continue
            if term in seen:
                continue
            seen.add(term)
            rows.append(term)
            if len(rows) >= limit:
                return rows
    return rows


def _build_primary_context(transcript_payload: dict[str, Any]) -> tuple[str, int, int]:
    segments = transcript_payload.get("segments", []) or []
    lines: list[str] = []

    cue_lines = _segment_cue_lines(segments)
    if cue_lines:
        lines.extend(cue_lines)

    extracted_terms = _extract_terms(segments)
    if extracted_terms:
        if lines:
            lines.append("")
        lines.append("frequent terms")
        lines.extend(extracted_terms)

    identifiers = _extract_identifiers(segments)
    if identifiers:
        if lines:
            lines.append("")
        lines.append("identifiers")
        lines.extend(identifiers)

    primary = "\n".join(lines).strip()
    return primary, len(segments), len(set(extracted_terms + identifiers))


def _truncate_text(value: str, limit: int) -> tuple[str, bool]:
    if limit <= 0:
        return "", bool(value)
    if len(value) <= limit:
        return value, False
    return value[:limit].rstrip(), True


def build_context_documents(
    *,
    transcript_dir: Path,
    transcript_payload: dict[str, Any],
    supplemental_context_text: str | None,
    max_merged_length: int = DEFAULT_MAX_MERGED_LENGTH,
) -> dict[str, Any]:
    transcript_dir.mkdir(parents=True, exist_ok=True)

    primary_context, source_segment_count, extracted_terms_count = _build_primary_context(
        transcript_payload
    )
    secondary_context = _normalize_multiline_text(supplemental_context_text)
    merged_parts = [part for part in (primary_context, secondary_context) if part]
    merged_context = "\n\n".join(merged_parts)
    merged_context, merged_truncated = _truncate_text(merged_context, max_merged_length)

    write_text(transcript_dir / "context_primary.txt", primary_context)
    if secondary_context:
        write_text(transcript_dir / "context_secondary.txt", secondary_context)
    elif (transcript_dir / "context_secondary.txt").exists():
        (transcript_dir / "context_secondary.txt").unlink()
    write_text(transcript_dir / "context_merged.txt", merged_context)

    report = {
        "builder_version": CONTEXT_BUILDER_VERSION,
        "primary_context_length": len(primary_context),
        "secondary_context_length": len(secondary_context),
        "merged_context_length": len(merged_context),
        "merged_context_truncated": merged_truncated,
        "primary_source_segment_count": source_segment_count,
        "extracted_terms_count": extracted_terms_count,
    }
    (transcript_dir / "context_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report

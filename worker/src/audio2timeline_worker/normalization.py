from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .fs_utils import now_iso, write_json_atomic, write_text


def normalize_normalization_mode(value: str | None) -> str:
    return "off" if str(value or "").strip().lower() == "off" else "deterministic"


def _normalize_multiline_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.strip() for line in normalized.split("\n")).strip()
    return normalized or None


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


@dataclass(frozen=True)
class TextRule:
    line_number: int
    sources: tuple[str, ...]
    target: str


@dataclass(frozen=True)
class SpeakerRule:
    line_number: int
    sources: tuple[str, ...]
    target: str


def _parse_glossary(
    glossary_text: str | None,
) -> tuple[list[TextRule], list[SpeakerRule], list[str], list[str]]:
    normalized = _normalize_multiline_text(glossary_text)
    if not normalized:
        return [], [], [], []

    text_rules: list[TextRule] = []
    speaker_rules: list[SpeakerRule] = []
    context_terms: list[str] = []
    warnings: list[str] = []

    for line_number, raw_line in enumerate(normalized.split("\n"), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("//"):
            continue

        if "=>" not in line:
            context_terms.append(line)
            continue

        left, right = [part.strip() for part in line.split("=>", 1)]
        if not left:
            warnings.append(f"Line {line_number}: missing source term before `=>`.")
            continue

        if left.lower().startswith("speaker:"):
            source_text = left[len("speaker:") :].strip()
            sources = tuple(
                sorted(
                    {item.strip() for item in source_text.split("|") if item.strip()},
                    key=len,
                    reverse=True,
                )
            )
            if not sources:
                warnings.append(f"Line {line_number}: speaker rule has no source labels.")
                continue
            speaker_rules.append(SpeakerRule(line_number=line_number, sources=sources, target=right))
            continue

        sources = tuple(
            sorted(
                {item.strip() for item in left.split("|") if item.strip()},
                key=len,
                reverse=True,
            )
        )
        if not sources:
            warnings.append(f"Line {line_number}: text rule has no source terms.")
            continue
        text_rules.append(TextRule(line_number=line_number, sources=sources, target=right))

    return text_rules, speaker_rules, context_terms, warnings


def _apply_speaker_rules(
    speaker: str,
    speaker_rules: list[SpeakerRule],
    rule_counts: dict[int, int],
) -> str:
    current = str(speaker or "SPEAKER_00")
    current_key = current.strip().lower()
    if not current_key:
        current_key = "speaker_00"
    for rule in speaker_rules:
        if any(current_key == source.lower() for source in rule.sources):
            if current != rule.target:
                rule_counts[rule.line_number] = rule_counts.get(rule.line_number, 0) + 1
            return rule.target
    return current


def _apply_text_rules(
    text: str,
    text_rules: list[TextRule],
    rule_counts: dict[int, int],
) -> str:
    current = _compact_text(text)
    for rule in text_rules:
        replacements = 0
        for source in rule.sources:
            if not source:
                continue
            count = current.count(source)
            if count <= 0:
                continue
            current = current.replace(source, rule.target)
            replacements += count
        if replacements > 0:
            rule_counts[rule.line_number] = rule_counts.get(rule.line_number, 0) + replacements
    return current


def _render_transcript_markdown(
    *,
    source_name: str,
    normalized_payload: dict[str, Any],
) -> str:
    metadata = normalized_payload.get("normalization", {}) or {}
    lines = [
        f"# Normalized Transcript: {source_name}",
        "",
        "## Metadata",
        "",
        f"- Normalization mode: `{metadata.get('mode', 'deterministic')}`",
        f"- Source transcript: `{metadata.get('source_variant', 'raw')}`",
        f"- Changed segments: `{metadata.get('changed_segment_count', 0)}` / `{metadata.get('segment_count', 0)}`",
        f"- Speaker rules applied: `{metadata.get('speaker_rule_count', 0)}`",
        f"- Text rules applied: `{metadata.get('text_rule_count', 0)}`",
        "",
        "## Transcript",
        "",
    ]
    segments = normalized_payload.get("segments", []) or []
    if not segments:
        lines.append("_No transcript segments generated._")
        return "\n".join(lines).rstrip() + "\n"

    for segment in segments:
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        speaker = str(segment.get("speaker") or "SPEAKER_00")
        text = _compact_text(segment.get("text"))
        lines.append(
            f"- [{_timestamp_label(start)} - {_timestamp_label(end)}] {speaker}: {text}"
        )
    return "\n".join(lines).rstrip() + "\n"


def _render_report_markdown(
    *,
    source_name: str,
    report_payload: dict[str, Any],
) -> str:
    lines = [
        f"# Normalization Report: {source_name}",
        "",
        f"- Mode: `{report_payload.get('mode', 'deterministic')}`",
        f"- Changed segments: `{report_payload.get('changed_segment_count', 0)}` / `{report_payload.get('segment_count', 0)}`",
        f"- Speaker rules: `{len(report_payload.get('speaker_rules', []))}`",
        f"- Text rules: `{len(report_payload.get('text_rules', []))}`",
        f"- Context terms: `{len(report_payload.get('context_terms', []))}`",
        "",
    ]

    speaker_rules = report_payload.get("speaker_rules", []) or []
    if speaker_rules:
        lines.extend(["## Speaker Rules", ""])
        for rule in speaker_rules:
            lines.append(
                f"- Line {rule['line_number']}: `{', '.join(rule['sources'])}` => `{rule['target']}` "
                f"(applied `{rule['applied_count']}` time(s))"
            )
        lines.append("")

    text_rules = report_payload.get("text_rules", []) or []
    if text_rules:
        lines.extend(["## Text Rules", ""])
        for rule in text_rules:
            lines.append(
                f"- Line {rule['line_number']}: `{', '.join(rule['sources'])}` => `{rule['target']}` "
                f"(applied `{rule['applied_count']}` time(s))"
            )
        lines.append("")

    context_terms = report_payload.get("context_terms", []) or []
    if context_terms:
        lines.extend(["## Context Terms", ""])
        for row in context_terms:
            lines.append(
                f"- `{row['term']}` appears `{row['occurrence_count']}` time(s) in the normalized transcript"
            )
        lines.append("")

    warnings = report_payload.get("warnings", []) or []
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def normalize_transcript_artifacts(
    *,
    source_name: str,
    transcript_dir: Any,
    raw_payload: dict[str, Any],
    normalization_mode: str | None,
    glossary_text: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    transcript_dir = transcript_dir
    mode = normalize_normalization_mode(normalization_mode)
    text_rules, speaker_rules, context_terms, warnings = _parse_glossary(glossary_text)

    raw_segments = raw_payload.get("segments", []) or []
    normalized_segments: list[dict[str, Any]] = []
    changed_segment_count = 0
    speaker_rule_counts: dict[int, int] = {}
    text_rule_counts: dict[int, int] = {}

    for segment in raw_segments:
        updated = dict(segment)
        original_speaker = str(updated.get("speaker") or "SPEAKER_00")
        original_text = _compact_text(updated.get("text"))
        speaker = original_speaker
        text = original_text

        if mode == "deterministic":
            speaker = _apply_speaker_rules(speaker, speaker_rules, speaker_rule_counts)
            text = _apply_text_rules(text, text_rules, text_rule_counts)

        updated["speaker"] = speaker
        updated["text"] = text
        if speaker != original_speaker or text != original_text:
            changed_segment_count += 1
        normalized_segments.append(updated)

    full_text = "\n".join(_compact_text(segment.get("text")) for segment in normalized_segments)
    context_rows = [
        {
            "term": term,
            "occurrence_count": full_text.count(term),
        }
        for term in context_terms
    ]

    normalization_metadata = {
        "mode": mode,
        "source_variant": "raw",
        "segment_count": len(normalized_segments),
        "changed_segment_count": changed_segment_count,
        "speaker_rule_count": sum(1 for rule in speaker_rules if speaker_rule_counts.get(rule.line_number, 0) > 0),
        "text_rule_count": sum(1 for rule in text_rules if text_rule_counts.get(rule.line_number, 0) > 0),
        "glossary_configured": bool(_normalize_multiline_text(glossary_text)),
    }
    normalized_payload = dict(raw_payload)
    normalized_payload["generated_at"] = now_iso()
    normalized_payload["segments"] = normalized_segments
    normalized_payload["normalization"] = normalization_metadata

    report_payload = {
        "status": "ok",
        "generated_at": now_iso(),
        "mode": mode,
        "segment_count": len(normalized_segments),
        "changed_segment_count": changed_segment_count,
        "speaker_rules": [
            {
                "line_number": rule.line_number,
                "sources": list(rule.sources),
                "target": rule.target,
                "applied_count": speaker_rule_counts.get(rule.line_number, 0),
            }
            for rule in speaker_rules
        ],
        "text_rules": [
            {
                "line_number": rule.line_number,
                "sources": list(rule.sources),
                "target": rule.target,
                "applied_count": text_rule_counts.get(rule.line_number, 0),
            }
            for rule in text_rules
        ],
        "context_terms": context_rows,
        "warnings": warnings,
    }

    write_json_atomic(transcript_dir / "normalized.json", normalized_payload)
    write_text(
        transcript_dir / "normalized.md",
        _render_transcript_markdown(source_name=source_name, normalized_payload=normalized_payload),
    )
    write_json_atomic(transcript_dir / "normalization_report.json", report_payload)
    write_text(
        transcript_dir / "normalization_report.md",
        _render_report_markdown(source_name=source_name, report_payload=report_payload),
    )
    return normalized_payload, report_payload

from __future__ import annotations

from pathlib import Path
from typing import Any

from .fs_utils import write_text


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _estimate_units(text: str) -> int:
    compact = _compact_text(text)
    if not compact:
        return 0
    if " " in compact:
        return len([token for token in compact.split(" ") if token])
    return len(compact)


def render_timeline(
    *,
    output_path: Path,
    source_info: dict[str, Any],
    transcript_payload: dict[str, Any],
    speaker_summary: dict[str, Any],
    audio_feature_summary: dict[str, Any],
) -> str:
    lines = [
        "# Audio Timeline",
        "",
        f"- Source: `{source_info.get('original_path') or source_info.get('resolved_path')}`",
        f"- Audio ID: `{source_info.get('audio_id') or source_info.get('media_id')}`",
        f"- Duration: `{source_info.get('duration_seconds', 0):.3f}s`",
        f"- Model: `{source_info.get('model_id') or transcript_payload.get('model', '')}`",
        f"- Diarization used: `{transcript_payload.get('diarization_used', False)}`",
        f"- Transcript normalization mode: `{transcript_payload.get('normalization', {}).get('mode') or source_info.get('transcript_normalization_mode') or 'off'}`",
        f"- Normalized segments changed: `{transcript_payload.get('normalization', {}).get('changed_segment_count', 0)}`",
        "",
        "## Summary",
        "",
        f"- Speakers: `{speaker_summary.get('speaker_count', 0)}`",
        f"- Silence seconds: `{audio_feature_summary.get('pause_summary', {}).get('total_silence_seconds')}`",
        f"- Loudness LUFS: `{audio_feature_summary.get('loudness_summary', {}).get('integrated_lufs')}`",
        f"- Estimated units/min: `{audio_feature_summary.get('speaking_rate_summary', {}).get('estimated_units_per_minute')}`",
        f"- Median pitch Hz: `{audio_feature_summary.get('pitch_summary', {}).get('median_hz')}`",
        f"- Overlap segments: `{audio_feature_summary.get('overlap_summary', {}).get('overlap_segment_count')}`",
        f"- Interruptions: `{audio_feature_summary.get('overlap_summary', {}).get('interruption_count')}`",
        f"- Speaker confidence mean ratio: `{audio_feature_summary.get('speaker_confidence_summary', {}).get('mean_best_overlap_ratio')}`",
        f"- Diarization quality: `{audio_feature_summary.get('diarization_quality_summary', {}).get('quality_band')}`",
        "",
    ]

    segments = transcript_payload.get("segments", []) or []
    if not segments:
        lines.extend(["_No transcript segments generated._", ""])
        rendered = "\n".join(lines).rstrip() + "\n"
        write_text(output_path, rendered)
        return rendered

    previous_end = 0.0
    for segment in segments:
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        speaker = str(segment.get("speaker") or "SPEAKER_00")
        text = _compact_text(segment.get("text"))
        segment_duration = max(0.001, end - start)
        units = _estimate_units(text)
        units_per_min = round(units * 60.0 / segment_duration, 1)
        pause_before = max(0.0, start - previous_end)
        overlap = max(0.0, previous_end - start)

        lines.extend(
            [
                f"## {_timestamp_label(start)} - {_timestamp_label(end)}",
                "",
                f"- Speaker: `{speaker}`",
                f"- Text: {text}",
                f"- Pause before: `{pause_before:.3f}s`",
                f"- Overlap with previous: `{overlap:.3f}s`",
                f"- Estimated units/min: `{units_per_min}`",
                "",
            ]
        )
        previous_end = max(previous_end, end)

    rendered = "\n".join(lines).rstrip() + "\n"
    write_text(output_path, rendered)
    return rendered

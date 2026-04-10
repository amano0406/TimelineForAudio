from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .ffmpeg_utils import detect_silences, run_command
from .fs_utils import write_text


def _round(value: float | int | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _estimate_units(text: str) -> int:
    compact = _compact_text(text)
    if not compact:
        return 0
    if " " in compact:
        return len([token for token in compact.split(" ") if token])
    return len(compact)


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _segment_bounds(segment: dict[str, Any]) -> tuple[float, float, str, str]:
    start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
    end = float(segment.get("original_end", segment.get("end", start)) or start)
    end = max(start, end)
    speaker = str(segment.get("speaker") or "SPEAKER_00")
    text = _compact_text(segment.get("text"))
    return start, end, speaker, text


def _effective_segments(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        transcript_payload.get("speaker_segments")
        or transcript_payload.get("segments")
        or transcript_payload.get("raw_segments")
        or []
    )


def build_overlap_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    if not segments:
        return {
            "available": False,
            "segment_count": 0,
            "speaker_change_count": 0,
            "overlap_segment_count": 0,
            "speaker_change_overlap_count": 0,
            "interruption_count": 0,
            "rapid_turn_count": 0,
            "total_overlap_seconds": None,
            "max_overlap_seconds": None,
        }

    speaker_change_count = 0
    overlap_segment_count = 0
    speaker_change_overlap_count = 0
    interruption_count = 0
    rapid_turn_count = 0
    total_overlap_seconds = 0.0
    max_overlap_seconds = 0.0
    previous_end = 0.0
    previous_speaker: str | None = None

    for segment in segments:
        start, end, speaker, _ = _segment_bounds(segment)
        pause_before = max(0.0, start - previous_end)
        overlap = max(0.0, previous_end - start)
        speaker_changed = previous_speaker is not None and speaker != previous_speaker

        if speaker_changed:
            speaker_change_count += 1
            if pause_before <= 0.2:
                rapid_turn_count += 1
        if overlap > 0:
            overlap_segment_count += 1
            total_overlap_seconds += overlap
            max_overlap_seconds = max(max_overlap_seconds, overlap)
            if speaker_changed:
                speaker_change_overlap_count += 1
                if overlap >= 0.15:
                    interruption_count += 1

        previous_end = max(previous_end, end)
        previous_speaker = speaker

    return {
        "available": True,
        "segment_count": len(segments),
        "speaker_change_count": speaker_change_count,
        "overlap_segment_count": overlap_segment_count,
        "speaker_change_overlap_count": speaker_change_overlap_count,
        "interruption_count": interruption_count,
        "rapid_turn_count": rapid_turn_count,
        "total_overlap_seconds": _round(total_overlap_seconds),
        "max_overlap_seconds": _round(max_overlap_seconds),
        "interruption_overlap_threshold_seconds": 0.15,
        "rapid_turn_pause_threshold_seconds": 0.2,
    }


def build_diarization_summaries(
    transcript_payload: dict[str, Any],
    *,
    duration_seconds: float,
    overlap_summary: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    diarization_used = bool(transcript_payload.get("diarization_used", False))
    speaker_turns = transcript_payload.get("speaker_turns", []) or []
    segments = _effective_segments(transcript_payload)

    if not diarization_used:
        reason = "Diarization was not used for this transcript."
        return (
            {
                "available": False,
                "reason": reason,
                "diarization_used": False,
            },
            {
                "available": False,
                "reason": reason,
                "diarization_used": False,
            },
        )

    if not speaker_turns or not segments:
        reason = "Diarization output did not include enough speaker turns to score alignment."
        return (
            {
                "available": False,
                "reason": reason,
                "diarization_used": True,
            },
            {
                "available": False,
                "reason": reason,
                "diarization_used": True,
            },
        )

    best_overlap_ratios: list[float] = []
    for segment in segments:
        start, end, _, _ = _segment_bounds(segment)
        segment_duration = max(0.001, end - start)
        best_overlap = 0.0
        for turn in speaker_turns:
            overlap = max(
                0.0,
                min(end, float(turn.get("end", end) or end))
                - max(start, float(turn.get("start", start) or start)),
            )
            best_overlap = max(best_overlap, overlap)
        best_overlap_ratios.append(best_overlap / segment_duration)

    sorted_ratios = sorted(best_overlap_ratios)
    low_confidence_threshold = 0.55
    low_confidence_segments = sum(1 for ratio in best_overlap_ratios if ratio < low_confidence_threshold)
    ambiguous_ratio = low_confidence_segments / max(len(best_overlap_ratios), 1)
    mean_ratio = sum(best_overlap_ratios) / max(len(best_overlap_ratios), 1)
    median_ratio = sorted_ratios[len(sorted_ratios) // 2]

    speaker_confidence_summary = {
        "available": True,
        "diarization_used": True,
        "method": "best_speaker_turn_overlap_ratio",
        "segment_count": len(best_overlap_ratios),
        "mean_best_overlap_ratio": _round(mean_ratio, 3),
        "median_best_overlap_ratio": _round(median_ratio, 3),
        "min_best_overlap_ratio": _round(sorted_ratios[0], 3),
        "max_best_overlap_ratio": _round(sorted_ratios[-1], 3),
        "low_confidence_threshold": low_confidence_threshold,
        "low_confidence_segments": low_confidence_segments,
        "low_confidence_fraction": _round(ambiguous_ratio, 3),
        "note": "Heuristic score derived from alignment between transcript segments and diarization speaker turns.",
    }

    if mean_ratio >= 0.85 and ambiguous_ratio <= 0.10:
        quality_band = "high"
    elif mean_ratio >= 0.65 and ambiguous_ratio <= 0.35:
        quality_band = "medium"
    else:
        quality_band = "low"

    total_turn_seconds = sum(
        max(
            0.0,
            float(turn.get("end", 0.0) or 0.0) - float(turn.get("start", 0.0) or 0.0),
        )
        for turn in speaker_turns
    )
    speaker_labels = {
        str(turn.get("speaker") or "SPEAKER_00")
        for turn in speaker_turns
        if str(turn.get("speaker") or "").strip()
    }
    diarization_quality_summary = {
        "available": True,
        "diarization_used": True,
        "quality_band": quality_band,
        "speaker_turn_count": len(speaker_turns),
        "speaker_count": len(speaker_labels),
        "turn_coverage_ratio": _round(total_turn_seconds / max(duration_seconds, 0.001), 3),
        "mean_best_overlap_ratio": speaker_confidence_summary["mean_best_overlap_ratio"],
        "ambiguous_segment_count": low_confidence_segments,
        "ambiguous_segment_fraction": speaker_confidence_summary["low_confidence_fraction"],
        "overlap_segment_count": overlap_summary.get("overlap_segment_count"),
        "interruption_count": overlap_summary.get("interruption_count"),
        "note": "Quality band is a heuristic based on segment-to-speaker-turn overlap ratios and ambiguity rate.",
    }
    return speaker_confidence_summary, diarization_quality_summary


def build_speaker_summary(transcript_payload: dict[str, Any]) -> dict[str, Any]:
    speakers: dict[str, dict[str, Any]] = {}
    for segment in _effective_segments(transcript_payload):
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        speaker = str(segment.get("speaker") or "SPEAKER_00")
        text = _compact_text(segment.get("text"))
        duration = max(0.0, end - start)
        units = _estimate_units(text)
        row = speakers.setdefault(
            speaker,
            {
                "speaker": speaker,
                "segment_count": 0,
                "speech_seconds": 0.0,
                "units": 0,
                "first_start": start,
                "last_end": end,
            },
        )
        row["segment_count"] += 1
        row["speech_seconds"] += duration
        row["units"] += units
        row["first_start"] = min(float(row["first_start"]), start)
        row["last_end"] = max(float(row["last_end"]), end)

    sorted_rows = sorted(
        speakers.values(),
        key=lambda row: (-float(row["speech_seconds"]), str(row["speaker"])),
    )
    for row in sorted_rows:
        speech_seconds = max(0.001, float(row["speech_seconds"]))
        row["speech_seconds"] = _round(speech_seconds)
        row["estimated_units_per_minute"] = _round(float(row["units"]) * 60.0 / speech_seconds, 1)
        row["first_start"] = _round(float(row["first_start"]))
        row["last_end"] = _round(float(row["last_end"]))

    return {
        "speaker_count": len(sorted_rows),
        "diarization_used": bool(transcript_payload.get("diarization_used", False)),
        "diarization_error": transcript_payload.get("diarization_error"),
        "speakers": sorted_rows,
    }


def write_speaker_summary(
    *,
    source_name: str,
    output_dir: Path,
    transcript_payload: dict[str, Any],
) -> dict[str, Any]:
    summary = build_speaker_summary(transcript_payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "speaker_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Speaker Summary: {source_name}",
        "",
        f"- Speaker count: `{summary['speaker_count']}`",
        f"- Diarization used: `{summary['diarization_used']}`",
        f"- Diarization error: `{summary.get('diarization_error') or ''}`",
        "",
    ]
    if not summary["speakers"]:
        lines.append("_No speaker segments were available._")
    else:
        for row in summary["speakers"]:
            lines.extend(
                [
                    f"## {row['speaker']}",
                    "",
                    f"- Segments: `{row['segment_count']}`",
                    f"- Speech seconds: `{row['speech_seconds']}`",
                    f"- Estimated units/min: `{row['estimated_units_per_minute']}`",
                    f"- Active window: `{_timestamp_label(float(row['first_start']))}` to `{_timestamp_label(float(row['last_end']))}`",
                    "",
                ]
            )
    write_text(output_dir / "speaker_summary.md", "\n".join(lines).rstrip() + "\n")
    return summary


def _parse_loudnorm(stderr: str) -> dict[str, Any]:
    match = re.search(r"\{\s*\"input_i\".*?\}", stderr, re.DOTALL)
    if not match:
        return {"available": False}
    payload = json.loads(match.group(0))
    return {
        "available": True,
        "integrated_lufs": _round(payload.get("input_i"), 2),
        "loudness_range_lu": _round(payload.get("input_lra"), 2),
        "true_peak_dbtp": _round(payload.get("input_tp"), 2),
        "threshold_lufs": _round(payload.get("input_thresh"), 2),
    }


def _compute_loudness(input_path: Path) -> dict[str, Any]:
    completed = run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(input_path),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    return _parse_loudnorm((completed.stderr or "") + "\n" + (completed.stdout or ""))


def _compute_pitch_and_voice_features(input_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        import librosa
        import numpy as np
    except Exception as exc:
        reason = f"Optional librosa analysis is unavailable: {exc}"
        return {"available": False, "reason": reason}, {"available": False, "reason": reason}

    try:
        y, sr = librosa.load(str(input_path), sr=None, mono=True)
        if y.size == 0:
            return {"available": False, "reason": "Audio was empty."}, {"available": False, "reason": "Audio was empty."}

        f0, _, _ = librosa.pyin(
            y,
            fmin=librosa.note_to_hz("C2"),
            fmax=librosa.note_to_hz("C7"),
        )
        voiced = f0[~np.isnan(f0)]
        pitch_summary = {
            "available": bool(voiced.size),
            "mean_hz": _round(float(np.mean(voiced)), 2) if voiced.size else None,
            "median_hz": _round(float(np.median(voiced)), 2) if voiced.size else None,
            "p10_hz": _round(float(np.percentile(voiced, 10)), 2) if voiced.size else None,
            "p90_hz": _round(float(np.percentile(voiced, 90)), 2) if voiced.size else None,
        }
        if not voiced.size:
            pitch_summary["reason"] = "No voiced frames were detected."

        rms = librosa.feature.rms(y=y)[0]
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        voice_summary = {
            "available": True,
            "rms_mean": _round(float(np.mean(rms)), 5),
            "spectral_centroid_mean_hz": _round(float(np.mean(centroid)), 2),
            "spectral_bandwidth_mean_hz": _round(float(np.mean(bandwidth)), 2),
            "spectral_rolloff_mean_hz": _round(float(np.mean(rolloff)), 2),
        }
        return pitch_summary, voice_summary
    except Exception as exc:
        reason = f"Optional librosa analysis failed: {exc}"
        return {"available": False, "reason": reason}, {"available": False, "reason": reason}


def analyze_audio(
    *,
    source_name: str,
    audio_path: Path,
    duration_seconds: float,
    transcript_payload: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    silences = detect_silences(audio_path)
    total_silence = sum(max(0.0, end - start) for start, end in silences)
    longest_silence = max((max(0.0, end - start) for start, end in silences), default=0.0)
    pause_summary = {
        "available": True,
        "count": len(silences),
        "total_silence_seconds": _round(total_silence),
        "longest_silence_seconds": _round(longest_silence),
        "speech_ratio": _round(
            max(0.0, duration_seconds - total_silence) / max(duration_seconds, 0.001),
            4,
        ),
    }

    segments = _effective_segments(transcript_payload)
    overlap_summary = build_overlap_summary(segments)
    voiced_seconds = 0.0
    total_units = 0
    total_chars = 0
    for segment in segments:
        start = float(segment.get("original_start", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("original_end", segment.get("end", start)) or start)
        text = _compact_text(segment.get("text"))
        voiced_seconds += max(0.0, end - start)
        total_units += _estimate_units(text)
        total_chars += len(text.replace(" ", ""))

    speaking_rate_summary = {
        "available": voiced_seconds > 0,
        "segment_count": len(segments),
        "voiced_seconds": _round(voiced_seconds),
        "estimated_units_per_minute": _round(total_units * 60.0 / max(voiced_seconds, 0.001), 1)
        if voiced_seconds > 0
        else None,
        "characters_per_minute": _round(total_chars * 60.0 / max(voiced_seconds, 0.001), 1)
        if voiced_seconds > 0
        else None,
    }

    loudness_summary = _compute_loudness(audio_path)
    pitch_summary, optional_voice_feature_summary = _compute_pitch_and_voice_features(audio_path)
    speaker_confidence_summary, diarization_quality_summary = build_diarization_summaries(
        transcript_payload,
        duration_seconds=duration_seconds,
        overlap_summary=overlap_summary,
    )

    payload = {
        "pause_summary": pause_summary,
        "loudness_summary": loudness_summary,
        "speaking_rate_summary": speaking_rate_summary,
        "pitch_summary": pitch_summary,
        "overlap_summary": overlap_summary,
        "speaker_confidence_summary": speaker_confidence_summary,
        "diarization_quality_summary": diarization_quality_summary,
        "optional_voice_feature_summary": optional_voice_feature_summary,
    }
    (output_dir / "audio_features.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Audio Feature Summary: {source_name}",
        "",
        "## Pause / Silence",
        "",
        f"- Count: `{pause_summary['count']}`",
        f"- Total silence seconds: `{pause_summary['total_silence_seconds']}`",
        f"- Longest silence seconds: `{pause_summary['longest_silence_seconds']}`",
        f"- Speech ratio: `{pause_summary['speech_ratio']}`",
        "",
        "## Loudness",
        "",
        f"- Available: `{loudness_summary.get('available', False)}`",
        f"- Integrated LUFS: `{loudness_summary.get('integrated_lufs')}`",
        f"- Loudness range LU: `{loudness_summary.get('loudness_range_lu')}`",
        f"- True peak dBTP: `{loudness_summary.get('true_peak_dbtp')}`",
        "",
        "## Speaking Rate",
        "",
        f"- Available: `{speaking_rate_summary['available']}`",
        f"- Estimated units/min: `{speaking_rate_summary.get('estimated_units_per_minute')}`",
        f"- Characters/min: `{speaking_rate_summary.get('characters_per_minute')}`",
        "",
        "## Pitch",
        "",
        f"- Available: `{pitch_summary.get('available', False)}`",
        f"- Mean Hz: `{pitch_summary.get('mean_hz')}`",
        f"- Median Hz: `{pitch_summary.get('median_hz')}`",
        "",
        "## Overlap / Interruptions",
        "",
        f"- Available: `{overlap_summary.get('available', False)}`",
        f"- Speaker changes: `{overlap_summary.get('speaker_change_count')}`",
        f"- Overlap segments: `{overlap_summary.get('overlap_segment_count')}`",
        f"- Total overlap seconds: `{overlap_summary.get('total_overlap_seconds')}`",
        f"- Interruptions: `{overlap_summary.get('interruption_count')}`",
        "",
        "## Optional Voice Features",
        "",
        f"- Available: `{optional_voice_feature_summary.get('available', False)}`",
        f"- RMS mean: `{optional_voice_feature_summary.get('rms_mean')}`",
        f"- Spectral centroid mean Hz: `{optional_voice_feature_summary.get('spectral_centroid_mean_hz')}`",
        f"- Spectral bandwidth mean Hz: `{optional_voice_feature_summary.get('spectral_bandwidth_mean_hz')}`",
        "",
        "## Speaker Confidence",
        "",
        f"- Available: `{speaker_confidence_summary['available']}`",
        f"- Mean best overlap ratio: `{speaker_confidence_summary.get('mean_best_overlap_ratio')}`",
        f"- Low-confidence segments: `{speaker_confidence_summary.get('low_confidence_segments')}`",
        f"- Note: {speaker_confidence_summary.get('note') or speaker_confidence_summary.get('reason')}",
        "",
        "## Diarization Quality",
        "",
        f"- Available: `{diarization_quality_summary.get('available', False)}`",
        f"- Quality band: `{diarization_quality_summary.get('quality_band')}`",
        f"- Speaker turns: `{diarization_quality_summary.get('speaker_turn_count')}`",
        f"- Ambiguous segments: `{diarization_quality_summary.get('ambiguous_segment_count')}`",
        f"- Note: {diarization_quality_summary.get('note') or diarization_quality_summary.get('reason')}",
        "",
    ]
    write_text(output_dir / "audio_features.md", "\n".join(lines))
    return payload

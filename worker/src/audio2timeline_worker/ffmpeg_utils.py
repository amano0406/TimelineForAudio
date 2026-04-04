from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .fs_utils import ensure_dir


def run_command(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _parse_optional_int(value: Any) -> int | None:
    if value in (None, "", "N/A"):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_ratio(value: Any) -> float | None:
    if value in (None, "", "N/A", "0/0"):
        return None

    text = str(value).strip()
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            denominator = float(right)
            if denominator == 0:
                return None
            return round(float(left) / denominator, 3)
        except (TypeError, ValueError):
            return None

    try:
        return round(float(text), 3)
    except (TypeError, ValueError):
        return None


def summarize_probe_payload(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    format_info = payload.get("format", {}) or {}
    streams = payload.get("streams", []) or []
    duration = float(format_info.get("duration") or 0.0)
    size = int(format_info.get("size") or path.stat().st_size)
    format_tags = format_info.get("tags") or {}
    stream_tags = (
        next(
            (
                stream.get("tags")
                for stream in streams
                if isinstance(stream.get("tags"), dict)
                and stream.get("tags", {}).get("creation_time")
            ),
            {},
        )
        or {}
    )
    creation_time = format_tags.get("creation_time") or stream_tags.get("creation_time")

    audio_stream = next(
        (stream for stream in streams if str(stream.get("codec_type") or "").lower() == "audio"),
        None,
    )

    format_name = str(format_info.get("format_name") or "").strip()
    if format_name:
        format_name = format_name.split(",", 1)[0].strip()

    return {
        "duration_seconds": duration,
        "size_bytes": size,
        "streams": streams,
        "captured_at": creation_time,
        "container_name": format_name or None,
        "extension": path.suffix.lower() or None,
        "audio_codec": str(audio_stream.get("codec_name") or "").strip() or None
        if audio_stream
        else None,
        "audio_channels": _parse_optional_int(audio_stream.get("channels")) if audio_stream else None,
        "audio_sample_rate": _parse_optional_int(audio_stream.get("sample_rate")) if audio_stream else None,
        "bitrate": _parse_optional_int(format_info.get("bit_rate"))
        or _parse_optional_int((audio_stream or {}).get("bit_rate")),
    }


def probe_audio(path: Path) -> dict[str, Any]:
    completed = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,format_name",
            "-show_streams",
            "-print_format",
            "json",
            str(path),
        ]
    )
    payload = json.loads(completed.stdout)
    return summarize_probe_payload(payload, path)


def extract_audio(source_path: Path, output_path: Path) -> None:
    ensure_dir(output_path.parent)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ]
    )


def detect_silences(input_path: Path) -> list[tuple[float, float]]:
    detected = run_command(
        [
            "ffmpeg",
            "-i",
            str(input_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.35",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    return _parse_silencedetect((detected.stderr or "") + "\n" + (detected.stdout or ""))


def _parse_silencedetect(stderr: str) -> list[tuple[float, float]]:
    starts: list[float] = []
    intervals: list[tuple[float, float]] = []
    start_pattern = re.compile(r"silence_start:\s*([0-9.]+)")
    end_pattern = re.compile(r"silence_end:\s*([0-9.]+)")
    for line in stderr.splitlines():
        start_match = start_pattern.search(line)
        if start_match:
            starts.append(float(start_match.group(1)))
            continue
        end_match = end_pattern.search(line)
        if end_match and starts:
            intervals.append((starts.pop(0), float(end_match.group(1))))
    return intervals


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _invert_intervals(
    duration: float, silences: list[tuple[float, float]], padding: float
) -> list[tuple[float, float]]:
    if duration <= 0:
        return []
    merged = _merge_intervals(silences)
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for silence_start, silence_end in merged:
        kept_start = cursor
        kept_end = max(cursor, silence_start - padding)
        if kept_end - kept_start >= 0.25:
            keep.append((kept_start, kept_end))
        cursor = min(duration, silence_end + padding)
    if duration - cursor >= 0.25:
        keep.append((cursor, duration))
    if not keep:
        return [(0.0, duration)]
    return keep


def trim_audio(
    input_path: Path, output_path: Path, duration_seconds: float
) -> list[dict[str, float]]:
    ensure_dir(output_path.parent)
    detected = run_command(
        [
            "ffmpeg",
            "-i",
            str(input_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.5",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    silences = _parse_silencedetect((detected.stderr or "") + "\n" + (detected.stdout or ""))
    keep_intervals = _invert_intervals(duration_seconds, silences, padding=1.0)
    if (
        len(keep_intervals) == 1
        and abs(keep_intervals[0][0]) < 0.001
        and abs(keep_intervals[0][1] - duration_seconds) < 0.001
    ):
        shutil.copy2(input_path, output_path)
    else:
        filter_parts: list[str] = []
        concat_labels: list[str] = []
        for idx, (start, end) in enumerate(keep_intervals):
            label = f"a{idx}"
            filter_parts.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[{label}]"
            )
            concat_labels.append(f"[{label}]")
        filter_parts.append(f"{''.join(concat_labels)}concat=n={len(keep_intervals)}:v=0:a=1[outa]")
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[outa]",
                str(output_path),
            ]
        )

    cut_map: list[dict[str, float]] = []
    trimmed_cursor = 0.0
    for original_start, original_end in keep_intervals:
        segment_duration = max(0.0, original_end - original_start)
        cut_map.append(
            {
                "original_start": round(original_start, 3),
                "original_end": round(original_end, 3),
                "trimmed_start": round(trimmed_cursor, 3),
                "trimmed_end": round(trimmed_cursor + segment_duration, 3),
            }
        )
        trimmed_cursor += segment_duration
    return cut_map


def extract_frame(video_path: Path, output_path: Path, timestamp: float) -> None:
    ensure_dir(output_path.parent)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]
    )

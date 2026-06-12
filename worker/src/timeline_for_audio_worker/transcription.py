from __future__ import annotations

import gc
import os
import json
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .runtime_profile import normalize_compute_mode

TRANSCRIPTION_BACKEND = "faster-whisper-large-v3-v1"
TRANSCRIPTION_MODEL_ID = "Systran/faster-whisper-large-v3"
_FASTER_WHISPER_MODEL_NAME = "large-v3"
_DEFAULT_CHUNK_SECONDS = 600.0


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start: float
    end: float
    text: str
    avg_logprob: float | None = None
    no_speech_probability: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    backend_name: str
    model_id: str
    status: str
    device: str
    compute_type: str
    language: str | None
    language_probability: float | None
    duration: float | None
    segments: list[TranscriptSegment]
    warnings: list[str]


@dataclass(frozen=True)
class LoadedTranscriptionModel:
    model: Any
    device: str
    compute_type: str


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _device_for_compute_mode(compute_mode: str | None) -> str:
    return "cuda" if normalize_compute_mode(compute_mode) == "gpu" else "cpu"


def _compute_type_for_compute_mode(compute_mode: str | None) -> str:
    override = str(os.environ.get("TIMELINE_FOR_AUDIO_WHISPER_COMPUTE_TYPE") or "").strip()
    if override:
        return override
    return "int8_float16" if normalize_compute_mode(compute_mode) == "gpu" else "int8"


def _transcription_chunk_seconds() -> float:
    value = str(os.environ.get("TIMELINE_FOR_AUDIO_TRANSCRIPTION_CHUNK_SECONDS") or "").strip()
    if value:
        try:
            return max(60.0, float(value))
        except ValueError:
            pass
    return _DEFAULT_CHUNK_SECONDS


def _probe_duration_seconds(audio_path: Any) -> float | None:
    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-print_format",
                "json",
                str(audio_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout or "{}")
        return float((payload.get("format") or {}).get("duration") or 0.0) or None
    except Exception:
        return None


def _extract_chunk(source_path: Any, output_path: Path, start: float, duration: float) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )


def _transcribe_chunk(
    loaded: LoadedTranscriptionModel,
    audio_path: Any,
) -> tuple[Any, Any]:
    return loaded.model.transcribe(
        str(audio_path),
        language=None,
        vad_filter=False,
        word_timestamps=False,
    )


@lru_cache(maxsize=2)
def _load_transcription_model(compute_mode: str) -> LoadedTranscriptionModel:
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError(f"faster-whisper is not available: {exc}") from exc

    device = _device_for_compute_mode(compute_mode)
    compute_type = _compute_type_for_compute_mode(compute_mode)
    model = WhisperModel(
        _FASTER_WHISPER_MODEL_NAME,
        device=device,
        compute_type=compute_type,
    )
    return LoadedTranscriptionModel(
        model=model,
        device=device,
        compute_type=compute_type,
    )


def release_transcription_resources() -> None:
    _load_transcription_model.cache_clear()
    gc.collect()
    try:
        import torch

        if getattr(torch.cuda, "is_available", lambda: False)():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except Exception:
        pass


def generate_transcript_segments(
    *,
    audio_path: Any,
    compute_mode: str | None = None,
) -> TranscriptionResult:
    loaded: LoadedTranscriptionModel | None = None
    info_items: list[Any] = []
    try:
        normalized_compute_mode = normalize_compute_mode(compute_mode)
        loaded = _load_transcription_model(normalized_compute_mode)
        segments: list[TranscriptSegment] = []
        segment_index = 1
        duration = _probe_duration_seconds(audio_path)
        chunk_seconds = _transcription_chunk_seconds()
        if duration is not None and duration > chunk_seconds:
            with tempfile.TemporaryDirectory(prefix="timeline-audio-transcribe-") as temp_dir:
                chunk_start = 0.0
                chunk_number = 0
                while chunk_start < duration:
                    chunk_duration = min(chunk_seconds, duration - chunk_start)
                    chunk_path = Path(temp_dir) / f"chunk-{chunk_number:04d}.wav"
                    _extract_chunk(audio_path, chunk_path, chunk_start, chunk_duration)
                    raw_segments, info = _transcribe_chunk(loaded, chunk_path)
                    info_items.append(info)
                    for segment in raw_segments:
                        text = _compact_text(getattr(segment, "text", ""))
                        if not text:
                            continue
                        start = chunk_start + float(getattr(segment, "start", 0.0) or 0.0)
                        end = chunk_start + float(getattr(segment, "end", 0.0) or 0.0)
                        segments.append(
                            TranscriptSegment(
                                index=segment_index,
                                start=start,
                                end=end,
                                text=text,
                                avg_logprob=_optional_float(
                                    getattr(segment, "avg_logprob", None)
                                ),
                                no_speech_probability=_optional_float(
                                    getattr(segment, "no_speech_prob", None)
                                ),
                            )
                        )
                        segment_index += 1
                    chunk_number += 1
                    chunk_start += chunk_duration
        else:
            raw_segments, info = _transcribe_chunk(loaded, audio_path)
            info_items.append(info)
            for segment in raw_segments:
                text = _compact_text(getattr(segment, "text", ""))
                if not text:
                    continue
                segments.append(
                    TranscriptSegment(
                        index=segment_index,
                        start=float(getattr(segment, "start", 0.0) or 0.0),
                        end=float(getattr(segment, "end", 0.0) or 0.0),
                        text=text,
                        avg_logprob=_optional_float(getattr(segment, "avg_logprob", None)),
                        no_speech_probability=_optional_float(
                            getattr(segment, "no_speech_prob", None)
                        ),
                    )
                )
                segment_index += 1
    except Exception as exc:
        return TranscriptionResult(
            backend_name=TRANSCRIPTION_BACKEND,
            model_id=TRANSCRIPTION_MODEL_ID,
            status="unavailable",
            device=loaded.device if loaded else _device_for_compute_mode(compute_mode),
            compute_type=loaded.compute_type
            if loaded
            else _compute_type_for_compute_mode(compute_mode),
            language=None,
            language_probability=None,
            duration=None,
            segments=[],
            warnings=[f"Speech transcription failed: {exc}"],
        )

    info = info_items[0] if info_items else None
    language = str(getattr(info, "language", "") or "").strip() or None
    return TranscriptionResult(
        backend_name=TRANSCRIPTION_BACKEND,
        model_id=TRANSCRIPTION_MODEL_ID,
        status="ok" if segments else "no_segments",
        device=loaded.device if loaded else _device_for_compute_mode(compute_mode),
        compute_type=loaded.compute_type
        if loaded
        else _compute_type_for_compute_mode(compute_mode),
        language=language,
        language_probability=_optional_float(getattr(info, "language_probability", None)),
        duration=_optional_float(getattr(info, "duration", None)) or duration,
        segments=segments,
        warnings=[] if segments else ["Speech transcription produced no segments."],
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def best_speaker_for_interval(
    start: float,
    end: float,
    speaker_turns: list[dict[str, Any]],
) -> str | None:
    midpoint = start + ((end - start) / 2.0)
    best_speaker: str | None = None
    best_overlap = 0.0
    for turn in speaker_turns:
        turn_start = float(turn.get("start", turn.get("original_start", 0.0)) or 0.0)
        turn_end = float(turn.get("end", turn.get("original_end", turn_start)) or turn_start)
        overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(turn.get("speaker") or "").strip() or None
    if best_overlap > 0:
        return best_speaker

    for turn in speaker_turns:
        turn_start = float(turn.get("start", turn.get("original_start", 0.0)) or 0.0)
        turn_end = float(turn.get("end", turn.get("original_end", turn_start)) or turn_start)
        if turn_start <= midpoint <= turn_end:
            return str(turn.get("speaker") or "").strip() or None
    return None

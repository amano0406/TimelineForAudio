from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from .runtime_profile import normalize_compute_mode

TRANSCRIPTION_BACKEND = "faster-whisper-large-v3-v1"
TRANSCRIPTION_MODEL_ID = "Systran/faster-whisper-large-v3"
_FASTER_WHISPER_MODEL_NAME = "large-v3"


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
    return "float16" if normalize_compute_mode(compute_mode) == "gpu" else "int8"


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


def generate_transcript_segments(
    *,
    audio_path: Any,
    compute_mode: str | None = None,
) -> TranscriptionResult:
    loaded: LoadedTranscriptionModel | None = None
    try:
        normalized_compute_mode = normalize_compute_mode(compute_mode)
        loaded = _load_transcription_model(normalized_compute_mode)
        raw_segments, info = loaded.model.transcribe(
            str(audio_path),
            language=None,
            vad_filter=False,
            word_timestamps=False,
        )
        segments: list[TranscriptSegment] = []
        for index, segment in enumerate(raw_segments, start=1):
            text = _compact_text(getattr(segment, "text", ""))
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    index=index,
                    start=float(getattr(segment, "start", 0.0) or 0.0),
                    end=float(getattr(segment, "end", 0.0) or 0.0),
                    text=text,
                    avg_logprob=_optional_float(getattr(segment, "avg_logprob", None)),
                    no_speech_probability=_optional_float(
                        getattr(segment, "no_speech_prob", None)
                    ),
                )
            )
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
        duration=_optional_float(getattr(info, "duration", None)),
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

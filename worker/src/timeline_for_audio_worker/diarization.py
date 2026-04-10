from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .settings import load_huggingface_token, load_settings

_DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
_ASCII_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
_LEADING_PUNCTUATION_RE = re.compile(r"^[,.;:!?)]")


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _segment_start(segment: dict[str, Any]) -> float:
    return float(
        segment.get("original_start", segment.get("start", segment.get("trimmed_start", 0.0))) or 0.0
    )


def _segment_end(segment: dict[str, Any]) -> float:
    start = _segment_start(segment)
    return float(
        segment.get("original_end", segment.get("end", segment.get("trimmed_end", start))) or start
    )


def _join_word_texts(words: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for word in words:
        piece = str(word.get("text") or "").strip()
        if not piece:
            continue
        if not parts:
            parts.append(piece)
            continue
        previous = parts[-1]
        if _LEADING_PUNCTUATION_RE.match(piece):
            parts[-1] = previous + piece
            continue
        if _ASCII_ALNUM_RE.search(previous[-1:]) and _ASCII_ALNUM_RE.match(piece[:1]):
            parts.append(f" {piece}")
            continue
        parts.append(piece)
    return _compact_text("".join(parts))


def _best_speaker_for_interval(
    start: float,
    end: float,
    diarization_rows: list[dict[str, Any]],
) -> tuple[str, float]:
    duration = max(0.001, end - start)
    best_speaker = "SPEAKER_00"
    best_overlap = 0.0
    midpoint = start + ((end - start) / 2.0)

    for row in diarization_rows:
        row_start = float(row.get("start", 0.0) or 0.0)
        row_end = float(row.get("end", row_start) or row_start)
        overlap = max(0.0, min(end, row_end) - max(start, row_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = str(row.get("speaker") or "SPEAKER_00")

    if best_overlap > 0:
        return best_speaker, round(best_overlap / duration, 3)

    for row in diarization_rows:
        row_start = float(row.get("start", 0.0) or 0.0)
        row_end = float(row.get("end", row_start) or row_start)
        if row_start <= midpoint <= row_end:
            return str(row.get("speaker") or "SPEAKER_00"), 0.0

    if not diarization_rows:
        return best_speaker, 0.0

    nearest = min(
        diarization_rows,
        key=lambda row: abs(
            midpoint
            - (
                float(row.get("start", 0.0) or 0.0)
                + (
                    float(row.get("end", row.get("start", 0.0)) or row.get("start", 0.0) or 0.0)
                    - float(row.get("start", 0.0) or 0.0)
                )
                / 2.0
            )
        ),
    )
    return str(nearest.get("speaker") or "SPEAKER_00"), 0.0


def _flatten_words(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(raw_segments, start=1):
        for word_index, word in enumerate(segment.get("words", []) or [], start=1):
            start = float(word.get("original_start", word.get("start", _segment_start(segment))) or _segment_start(segment))
            end = float(word.get("original_end", word.get("end", start)) or start)
            flattened.append(
                {
                    "index": len(flattened) + 1,
                    "source_segment_index": int(segment.get("index", segment_index) or segment_index),
                    "word_index": word_index,
                    "text": str(word.get("text") or ""),
                    "original_start": start,
                    "original_end": max(start, end),
                }
            )
    return flattened


def _build_speaker_segments_from_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for word in words:
        if not str(word.get("text") or "").strip():
            continue
        if rows:
            previous = rows[-1]
            if (
                previous.get("speaker") == word.get("speaker")
                and float(word.get("original_start", 0.0) or 0.0)
                <= float(previous.get("original_end", 0.0) or 0.0) + 0.15
            ):
                previous_words = previous.setdefault("_words", [])
                previous_words.append(word)
                previous["original_end"] = max(
                    float(previous.get("original_end", 0.0) or 0.0),
                    float(word.get("original_end", 0.0) or 0.0),
                )
                previous["text"] = _join_word_texts(previous_words)
                continue

        rows.append(
            {
                "index": len(rows) + 1,
                "speaker": str(word.get("speaker") or "SPEAKER_00"),
                "original_start": float(word.get("original_start", 0.0) or 0.0),
                "original_end": float(word.get("original_end", 0.0) or 0.0),
                "text": _compact_text(word.get("text")),
                "_words": [word],
            }
        )

    for row in rows:
        row.pop("_words", None)
    return rows


def _build_speaker_segments_from_segments(
    raw_segments: list[dict[str, Any]],
    diarization_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(raw_segments, start=1):
        start = _segment_start(segment)
        end = _segment_end(segment)
        speaker, ratio = _best_speaker_for_interval(start, end, diarization_rows)
        row = deepcopy(segment)
        row["index"] = int(segment.get("index", segment_index) or segment_index)
        row["speaker"] = speaker
        row["speaker_overlap_ratio"] = ratio
        rows.append(row)
    return rows


def merge_diarization_into_transcript(
    transcript_payload: dict[str, Any],
    diarization_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = deepcopy(transcript_payload)
    raw_segments = deepcopy(payload.get("raw_segments") or payload.get("segments") or [])
    payload["raw_segments"] = raw_segments

    flattened_words = _flatten_words(raw_segments)
    if not diarization_rows:
        payload["diarization_used"] = False
        payload["speaker_assignment_method"] = "none"
        payload["speaker_turns"] = []
        payload["speaker_segments"] = deepcopy(payload.get("speaker_segments") or raw_segments)
        payload["segments"] = deepcopy(payload["speaker_segments"])
        payload["words"] = flattened_words
        return payload

    if flattened_words:
        for word in flattened_words:
            speaker, ratio = _best_speaker_for_interval(
                float(word.get("original_start", 0.0) or 0.0),
                float(word.get("original_end", 0.0) or 0.0),
                diarization_rows,
            )
            word["speaker"] = speaker
            word["speaker_overlap_ratio"] = ratio

        speaker_segments = _build_speaker_segments_from_words(flattened_words)
        assignment_method = "word_overlap_midpoint"
    else:
        speaker_segments = _build_speaker_segments_from_segments(raw_segments, diarization_rows)
        assignment_method = "segment_overlap_fallback"

    payload["diarization_used"] = True
    payload["speaker_assignment_method"] = assignment_method
    payload["speaker_turns"] = deepcopy(diarization_rows)
    payload["speaker_segments"] = speaker_segments
    payload["segments"] = deepcopy(speaker_segments)
    payload["words"] = flattened_words
    return payload


def _iterate_diarization_rows(diarization_output: Any) -> list[dict[str, Any]]:
    annotation = getattr(diarization_output, "exclusive_speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = getattr(diarization_output, "speaker_diarization", None)
    if annotation is None or not hasattr(annotation, "itertracks"):
        annotation = diarization_output

    rows: list[dict[str, Any]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        rows.append(
            {
                "start": float(turn.start),
                "end": float(turn.end),
                "speaker": str(speaker),
            }
        )
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_diarization_audio_input(audio_path: Path) -> dict[str, Any]:
    try:
        import torchaudio
    except Exception as exc:
        raise RuntimeError(f"torchaudio is not available: {exc}") from exc

    waveform, sample_rate = torchaudio.load(str(audio_path))
    if hasattr(waveform, "dim") and callable(getattr(waveform, "dim")) and waveform.dim() == 1:
        waveform = waveform.unsqueeze(0)
    return {
        "waveform": waveform,
        "sample_rate": int(sample_rate),
    }


def apply_speaker_diarization(
    *,
    source_name: str,
    audio_path: Path,
    transcript_dir: Path,
    analysis_dir: Path | None,
    transcript_payload: dict[str, Any],
    compute_mode: str | None = None,
    artifact_stem: str | None = None,
) -> dict[str, Any]:
    from .transcribe import _write_transcript_payload

    artifact_name = str(artifact_stem or transcript_payload.get("pass_name") or "pass2")
    settings = load_settings()
    token = load_huggingface_token()
    diarization_requested = bool(transcript_payload.get("diarization_requested", False))
    terms_confirmed = bool(settings.get("huggingfaceTermsConfirmed"))
    diarization_rows: list[dict[str, Any]] = []
    diarization_error: str | None = None

    if diarization_requested and not token:
        diarization_error = "Hugging Face token is not configured."
    elif diarization_requested and not terms_confirmed:
        diarization_error = "Hugging Face gated model terms are not confirmed."
    elif diarization_requested:
        try:
            from pyannote.audio import Pipeline
        except Exception as exc:
            diarization_error = f"pyannote.audio is not available: {exc}"
        else:
            try:
                diarizer = Pipeline.from_pretrained(_DIARIZATION_MODEL_ID, token=token)
                target_compute_mode = str(
                    compute_mode
                    or transcript_payload.get("effective_compute_mode")
                    or transcript_payload.get("requested_compute_mode")
                    or "cpu"
                ).lower()
                if target_compute_mode == "gpu":
                    try:
                        import torch

                        if getattr(torch.cuda, "is_available", lambda: False)() and hasattr(diarizer, "to"):
                            diarizer.to(torch.device("cuda"))
                    except Exception:
                        pass
                audio_input = _load_diarization_audio_input(audio_path)
                diarization_rows = _iterate_diarization_rows(diarizer(audio_input))
            except Exception as exc:
                diarization_error = str(exc)

    enriched = merge_diarization_into_transcript(transcript_payload, diarization_rows)
    enriched["diarization_requested"] = diarization_requested
    enriched["diarization_error"] = diarization_error
    enriched["diarization_backend"] = "pyannote.audio"
    enriched["diarization_model_id"] = _DIARIZATION_MODEL_ID
    if not diarization_rows:
        enriched["diarization_used"] = False

    transcript_dir.mkdir(parents=True, exist_ok=True)
    _write_json(transcript_dir / f"{artifact_name}_words.json", enriched.get("words", []))
    _write_json(transcript_dir / f"{artifact_name}_speaker_spans.json", enriched.get("speaker_segments", []))
    if analysis_dir is not None:
        _write_json(analysis_dir / "diarization_turns.json", enriched.get("speaker_turns", []))

    _write_transcript_payload(
        source_name=source_name,
        transcript_dir=transcript_dir,
        artifact_stem=artifact_name,
        metadata=enriched,
    )
    return enriched

from __future__ import annotations

import gc
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .fs_utils import now_iso, write_text
from .runtime_profile import (
    TRANSCRIPTION_LANGUAGE,
    normalize_compute_mode,
    normalize_processing_quality as _normalize_processing_quality,
    resolve_model_name_for_quality as _resolve_model_name_for_quality,
    resolve_runtime_lane,
)
from .settings import load_huggingface_token, load_settings


def normalize_processing_quality(value: str | None) -> str:
    return _normalize_processing_quality(value)


def resolve_model_name_for_quality(value: str | None) -> str:
    return _resolve_model_name_for_quality(value)


def _is_cuda_oom(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "out of memory" in message or "cuda failed with error out of memory" in message


def _is_cuda_runtime_failure(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return (
        "cuda failed with error" in message
        or "cuda error" in message
        or "cublas" in message
        or "cudnn" in message
    )


def _initial_batch_size(device: str, processing_quality: str) -> int:
    if device != "cuda":
        return 8
    return 4 if normalize_processing_quality(processing_quality) == "high" else 16


def _candidate_batch_sizes(initial: int) -> list[int]:
    values = [initial, 12, 8, 6, 4, 2, 1]
    rows: list[int] = []
    for value in values:
        if value <= initial and value not in rows:
            rows.append(value)
    return rows


def _clear_torch_memory(torch_module: Any) -> None:
    gc.collect()
    cuda = getattr(torch_module, "cuda", None)
    is_available = getattr(cuda, "is_available", None)
    empty_cache = getattr(cuda, "empty_cache", None)
    if callable(is_available) and is_available() and callable(empty_cache):
        empty_cache()


def _load_model_with_fallback(
    *,
    load_model: Callable[[str, str], Any],
    torch_module: Any,
    initial_device: str,
    initial_compute_type: str,
    initial_batch_size: int,
    transcription_warnings: list[str],
) -> tuple[Any, str, str, int]:
    attempts: list[tuple[str, str, int, str | None]] = []

    if initial_device == "cuda":
        attempts.extend(
            [
                ("cuda", initial_compute_type, initial_batch_size, None),
                (
                    "cuda",
                    "int8_float16",
                    min(initial_batch_size, 8),
                    "Primary GPU compute type failed to load; using int8_float16 instead.",
                ),
                (
                    "cpu",
                    "int8",
                    4,
                    "GPU model loading failed; transcription fell back to CPU.",
                ),
            ]
        )
    else:
        attempts.append(("cpu", initial_compute_type, initial_batch_size, None))

    last_error: Exception | None = None
    for attempt_device, attempt_compute_type, batch_size, warning in attempts:
        if warning:
            transcription_warnings.append(warning)
        try:
            model = load_model(attempt_device, attempt_compute_type)
            return model, attempt_device, attempt_compute_type, batch_size
        except Exception as exc:
            last_error = exc
            if attempt_device != "cuda":
                raise
            _clear_torch_memory(torch_module)

    if last_error is not None:
        raise last_error
    raise RuntimeError("Model loading did not produce a transcription model.")


@dataclass
class SegmentRecord:
    index: int
    trimmed_start: float
    trimmed_end: float
    original_start: float
    original_end: float
    speaker: str
    text: str


def _map_trimmed_to_original(seconds: float, cut_map: list[dict[str, float]]) -> float:
    if not cut_map:
        return seconds
    for item in cut_map:
        if item["trimmed_start"] <= seconds <= item["trimmed_end"]:
            return item["original_start"] + (seconds - item["trimmed_start"])
    last = cut_map[-1]
    if seconds > last["trimmed_end"]:
        return last["original_end"]
    return seconds


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalize_prompt(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalized or None


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _build_word_rows(segment: Any, cut_map: list[dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for word_index, word in enumerate(getattr(segment, "words", []) or [], start=1):
        word_start = float(getattr(word, "start", getattr(segment, "start", 0.0)) or 0.0)
        word_end = float(getattr(word, "end", word_start) or word_start)
        rows.append(
            {
                "index": word_index,
                "trimmed_start": word_start,
                "trimmed_end": max(word_start, word_end),
                "original_start": _map_trimmed_to_original(word_start, cut_map),
                "original_end": _map_trimmed_to_original(word_end, cut_map),
                "text": str(getattr(word, "word", None) or getattr(word, "text", "") or ""),
            }
        )
    return rows


def _build_records(
    segments: list[dict[str, Any]],
) -> list[SegmentRecord]:
    records: list[SegmentRecord] = []
    for idx, segment in enumerate(segments, start=1):
        start = float(
            segment.get("trimmed_start", segment.get("start", segment.get("original_start", 0.0)))
            or 0.0
        )
        end = float(
            segment.get("trimmed_end", segment.get("end", segment.get("original_end", start)))
            or start
        )
        text = _normalize_text(segment.get("text"))
        if not text:
            continue
        speaker = str(segment.get("speaker") or "SPEAKER_00")
        records.append(
            SegmentRecord(
                index=idx,
                trimmed_start=start,
                trimmed_end=end,
                original_start=float(segment.get("original_start", start) or start),
                original_end=float(segment.get("original_end", end) or end),
                speaker=speaker,
                text=text,
            )
        )
    return records


def _render_markdown(
    source_name: str, metadata: dict[str, Any], segments: list[SegmentRecord]
) -> str:
    lines = [
        f"# Transcript: {source_name}",
        "",
        "## Metadata",
        "",
        f"- Pass: `{metadata.get('pass_name', '')}`",
        f"- Model: `{metadata['model']}`",
        f"- Processing quality: `{metadata.get('processing_quality', 'standard')}`",
        f"- Language: `{metadata['language']}`",
        f"- Device: `{metadata['device']}`",
        f"- Requested compute mode: `{metadata.get('requested_compute_mode', 'cpu')}`",
        f"- Effective compute mode: `{metadata.get('effective_compute_mode', metadata['device'])}`",
        f"- GPU available: `{metadata.get('gpu_available', False)}`",
        f"- Compute type: `{metadata['compute_type']}`",
        f"- Batch size: `{metadata.get('batch_size', '')}`",
        f"- Alignment used: `{metadata['alignment_used']}`",
        f"- Context prompt configured: `{metadata.get('context_prompt_configured', False)}`",
        f"- Context prompt length: `{metadata.get('context_prompt_length', 0)}`",
        f"- Diarization requested: `{metadata.get('diarization_requested', False)}`",
        f"- Diarization used: `{metadata['diarization_used']}`",
        f"- Diarization error: `{metadata.get('diarization_error') or ''}`",
        "",
        "## Warnings",
        "",
    ]
    warnings = [
        str(item).strip()
        for item in metadata.get("transcription_warnings", [])
        if str(item).strip()
    ]
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("_None._")
    lines.extend(
        [
            "",
            "## Transcript",
            "",
        ]
    )
    if not segments:
        lines.append("_No transcript segments generated._")
        return "\n".join(lines) + "\n"
    for segment in segments:
        lines.append(
            f"- [{_timestamp_label(segment.original_start)} - {_timestamp_label(segment.original_end)}] "
            f"{segment.speaker}: {segment.text}"
        )
    return "\n".join(lines) + "\n"


def _records_from_payload_segments(segments: list[dict[str, Any]]) -> list[SegmentRecord]:
    rows: list[SegmentRecord] = []
    for index, segment in enumerate(segments, start=1):
        trimmed_start = float(
            segment.get("trimmed_start", segment.get("start", segment.get("original_start", 0.0)))
            or 0.0
        )
        trimmed_end = float(
            segment.get("trimmed_end", segment.get("end", segment.get("original_end", trimmed_start)))
            or trimmed_start
        )
        original_start = float(segment.get("original_start", trimmed_start) or trimmed_start)
        original_end = float(segment.get("original_end", trimmed_end) or trimmed_end)
        rows.append(
            SegmentRecord(
                index=int(segment.get("index", index) or index),
                trimmed_start=trimmed_start,
                trimmed_end=max(trimmed_start, trimmed_end),
                original_start=original_start,
                original_end=max(original_start, original_end),
                speaker=str(segment.get("speaker") or "SPEAKER_00"),
                text=_normalize_text(segment.get("text")),
            )
        )
    return rows


def _write_transcript_payload(
    *,
    source_name: str,
    transcript_dir: Path,
    artifact_stem: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    transcript_dir.mkdir(parents=True, exist_ok=True)
    rendered_segments = (
        metadata.get("speaker_segments")
        or metadata.get("segments")
        or metadata.get("raw_segments")
        or []
    )
    records = _records_from_payload_segments(rendered_segments)
    (transcript_dir / f"{artifact_stem}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_text(
        transcript_dir / f"{artifact_stem}.md",
        _render_markdown(source_name, metadata, records),
    )
    return metadata


def _error_payload(
    *,
    source_name: str,
    transcript_dir: Path,
    artifact_stem: str,
    pass_name: str,
    error_message: str,
    processing_quality: str | None,
    context_prompt: str | None,
    diarization_requested: bool,
) -> dict[str, Any]:
    resolved_context_prompt = _normalize_prompt(context_prompt)
    payload = {
        "status": "error",
        "pass_name": pass_name,
        "error": error_message,
        "generated_at": now_iso(),
        "model": resolve_model_name_for_quality(processing_quality),
        "processing_quality": normalize_processing_quality(processing_quality),
        "model_id": resolve_model_name_for_quality(processing_quality),
        "device": "cpu",
        "requested_compute_mode": "cpu",
        "effective_compute_mode": "cpu",
        "gpu_available": False,
        "compute_type": "int8",
        "batch_size": 4,
        "language": TRANSCRIPTION_LANGUAGE,
        "language_probability": None,
        "alignment_used": False,
        "context_prompt_configured": bool(resolved_context_prompt),
        "context_prompt_sha256": (
            hashlib.sha256(resolved_context_prompt.encode("utf-8")).hexdigest()
            if resolved_context_prompt
            else None
        ),
        "context_prompt_length": len(resolved_context_prompt or ""),
        "diarization_requested": diarization_requested,
        "diarization_used": False,
        "diarization_error": None,
        "transcription_warnings": [],
        "segments": [],
        "speaker_segments": [],
        "raw_segments": [],
        "words": [],
        "speaker_assignment_method": "none",
        "speaker_turns": [],
    }
    return _write_transcript_payload(
        source_name=source_name,
        transcript_dir=transcript_dir,
        artifact_stem=artifact_stem,
        metadata=payload,
    )


def transcribe_audio(
    *,
    source_name: str,
    audio_path: Path,
    transcript_dir: Path,
    artifact_stem: str,
    pass_name: str,
    cut_map: list[dict[str, float]],
    compute_mode: str | None = None,
    processing_quality: str | None = None,
    initial_prompt: str | None = None,
    diarization_enabled: bool = True,
) -> dict[str, Any]:
    settings = load_settings()

    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
    except Exception as exc:
        return _error_payload(
            source_name=source_name,
            transcript_dir=transcript_dir,
            artifact_stem=artifact_stem,
            pass_name=pass_name,
            error_message=f"faster-whisper is not available: {exc}",
            processing_quality=processing_quality,
            context_prompt=initial_prompt,
            diarization_requested=diarization_enabled,
        )

    try:
        import torch
    except Exception:
        class _CudaShim:
            @staticmethod
            def is_available() -> bool:
                return False

            @staticmethod
            def empty_cache() -> None:
                return None

        class _TorchShim:
            cuda = _CudaShim()

        torch = _TorchShim()

    requested_compute_mode = normalize_compute_mode(compute_mode or settings.get("computeMode"))
    gpu_available = bool(getattr(torch.cuda, "is_available", lambda: False)())
    runtime_lane = resolve_runtime_lane(requested_compute_mode, processing_quality or settings.get("processingQuality"))
    device = "cuda" if requested_compute_mode == "gpu" and gpu_available else "cpu"
    effective_compute_mode = "gpu" if device == "cuda" else "cpu"
    compute_type = runtime_lane.compute_types[0] if device == "cuda" else "int8"
    resolved_quality = runtime_lane.processing_quality
    model_name = runtime_lane.model_id
    language = TRANSCRIPTION_LANGUAGE
    resolved_initial_prompt = _normalize_prompt(initial_prompt)

    transcription_warnings: list[str] = []
    batch_size = _initial_batch_size(device, resolved_quality)

    def load_transcription_model(target_device: str, target_compute_type: str) -> Any:
        whisper_model = WhisperModel(
            model_name,
            device=target_device,
            compute_type=target_compute_type,
        )
        return BatchedInferencePipeline(model=whisper_model)

    model, device, compute_type, batch_size = _load_model_with_fallback(
        load_model=load_transcription_model,
        torch_module=torch,
        initial_device=device,
        initial_compute_type=compute_type,
        initial_batch_size=batch_size,
        transcription_warnings=transcription_warnings,
    )
    effective_compute_mode = "gpu" if device == "cuda" else "cpu"

    segment_rows: list[dict[str, Any]] | None = None
    info: Any = None
    last_error: Exception | None = None
    cpu_fallback_warning: str | None = None

    for candidate_batch_size in _candidate_batch_sizes(batch_size):
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=language,
                batch_size=candidate_batch_size,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=resolved_initial_prompt,
                word_timestamps=pass_name == "pass2",
            )
            segment_rows = [
                {
                    "index": index,
                    "trimmed_start": float(segment.start),
                    "trimmed_end": float(getattr(segment, "end", segment.start) or segment.start),
                    "original_start": _map_trimmed_to_original(float(segment.start), cut_map),
                    "original_end": _map_trimmed_to_original(float(getattr(segment, "end", segment.start) or segment.start), cut_map),
                    "text": getattr(segment, "text", ""),
                    "speaker": "SPEAKER_00",
                    "words": _build_word_rows(segment, cut_map),
                }
                for index, segment in enumerate(list(segments), start=1)
            ]
            batch_size = candidate_batch_size
            if device == "cuda" and candidate_batch_size != _initial_batch_size(
                device, resolved_quality
            ):
                transcription_warnings.append(
                    f"GPU batch size was reduced to {candidate_batch_size} to fit available memory."
                )
            break
        except Exception as exc:
            if device != "cuda":
                raise
            last_error = exc
            _clear_torch_memory(torch)
            if _is_cuda_oom(exc):
                cpu_fallback_warning = (
                    "GPU memory was insufficient for this audio; transcription fell back to CPU."
                )
                continue
            if _is_cuda_runtime_failure(exc):
                cpu_fallback_warning = (
                    "GPU transcription failed with a CUDA runtime error; transcription fell back to CPU."
                )
                break
            raise

    if segment_rows is None and device == "cuda":
        try:
            del model
        except Exception:
            pass
        _clear_torch_memory(torch)
        device = "cpu"
        effective_compute_mode = "cpu"
        compute_type = "int8"
        batch_size = 4
        transcription_warnings.append(
            cpu_fallback_warning
            or "GPU transcription failed on CUDA; transcription fell back to CPU."
        )
        model = load_transcription_model(device, compute_type)
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            batch_size=batch_size,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            initial_prompt=resolved_initial_prompt,
            word_timestamps=pass_name == "pass2",
        )
        segment_rows = [
            {
                "index": index,
                "trimmed_start": float(segment.start),
                "trimmed_end": float(getattr(segment, "end", segment.start) or segment.start),
                "original_start": _map_trimmed_to_original(float(segment.start), cut_map),
                "original_end": _map_trimmed_to_original(float(getattr(segment, "end", segment.start) or segment.start), cut_map),
                "text": getattr(segment, "text", ""),
                "speaker": "SPEAKER_00",
                "words": _build_word_rows(segment, cut_map),
            }
            for index, segment in enumerate(list(segments), start=1)
        ]

    if segment_rows is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Transcription did not produce a result.")

    if not any(_normalize_text(segment.get("text")) for segment in segment_rows):
        transcription_warnings.append("No speech was transcribed after VAD.")

    records = _build_records(segment_rows)
    words = [word for segment in segment_rows for word in segment.get("words", []) or []]
    payload = {
        "status": "ok",
        "pass_name": pass_name,
        "generated_at": now_iso(),
        "model": model_name,
        "processing_quality": resolved_quality,
        "model_id": model_name,
        "runtime_lane": runtime_lane.lane_id,
        "device": device,
        "requested_compute_mode": requested_compute_mode,
        "effective_compute_mode": effective_compute_mode,
        "gpu_available": gpu_available,
        "compute_type": compute_type,
        "batch_size": batch_size,
        "language": getattr(info, "language", None) or language,
        "language_probability": getattr(info, "language_probability", None),
        "context_prompt_configured": bool(resolved_initial_prompt),
        "context_prompt_sha256": (
            hashlib.sha256(resolved_initial_prompt.encode("utf-8")).hexdigest()
            if resolved_initial_prompt
            else None
        ),
        "context_prompt_length": len(resolved_initial_prompt or ""),
        "alignment_used": False,
        "diarization_requested": diarization_enabled,
        "diarization_used": False,
        "diarization_error": None,
        "transcription_warnings": transcription_warnings,
        "segments": [asdict(record) for record in records],
        "speaker_segments": [asdict(record) for record in records],
        "raw_segments": segment_rows,
        "words": words,
        "speaker_assignment_method": "none",
        "speaker_turns": [],
    }
    _write_transcript_payload(
        source_name=source_name,
        transcript_dir=transcript_dir,
        artifact_stem=artifact_stem,
        metadata=payload,
    )
    del model
    _clear_torch_memory(torch)
    return payload

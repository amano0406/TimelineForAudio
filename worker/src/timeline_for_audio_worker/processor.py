from __future__ import annotations

import json
import os
import re
import shutil
import threading
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from .catalog import append_catalog_rows, catalog_key, catalog_path, load_catalog
from .contracts import RunRequest, RunResult, RunStatus, ManifestItem
from .diarization import generate_speaker_turns
from .eta import build_eta_predictor, estimate_remaining_seconds
from .ffmpeg_utils import extract_audio, probe_audio, trim_audio
from .fs_utils import (
    append_log,
    ensure_dir,
    now_iso,
    read_json,
    short_id,
    slugify,
    tail_text,
    write_json_atomic,
    write_text,
)
from .hashing import sha256_file
from .progress import (
    completed_item_count,
    completed_progress_percent,
    current_item_stage_fraction,
    overall_progress_percent,
)
from .settings import appdata_root, configured_path, load_settings, uploads_root
from .transcription import (
    TRANSCRIPTION_BACKEND,
    TRANSCRIPTION_MODEL_ID,
    best_speaker_for_interval,
    generate_transcript_segments,
)
from .runtime_profile import assert_runtime_supports_compute_mode
from .vad_profile import vad_config_for_profile

_RUN_LOCK_STALE_AFTER = timedelta(seconds=30)
_MIN_PREPROCESS_DURATION_SEC = 2.0
_PREFLIGHT_SKIPPED_STATUSES = {"skipped_invalid", "skipped_too_short"}
_DELETE_REQUEST_MARKER = ".delete-requested"
_INTERRUPTED_RUN_MESSAGE = (
    "Run was interrupted while the worker was stopped. It will not be resumed "
    "automatically; queue a new refresh to retry."
)
_MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC = 0.1
_HIGH_NO_SPEECH_PROBABILITY = 0.6
_LOW_TRANSCRIPT_CONFIDENCE = -0.6
_KNOWN_SILENCE_HALLUCINATION_PHRASES = {
    "ご視聴ありがとうございました",
    "ご視聴ありがとうございます",
    "ありがとうございました",
    "Thank you for watching",
    "Thanks for watching",
}


class RunDeletionRequested(RuntimeError):
    pass


def _run_log_path(run_dir: Path) -> Path:
    return run_dir / "logs" / "worker.log"


def _runtime_runs_root(output_root_path: Path) -> Path:
    try:
        normalized = str(output_root_path.resolve(strict=False))
    except Exception:
        normalized = str(output_root_path)
    key = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()[:16]
    return appdata_root() / key / "runs"


def _status_path(run_dir: Path) -> Path:
    return run_dir / "status.json"


def _result_path(run_dir: Path) -> Path:
    return run_dir / "result.json"


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def _request_path(run_dir: Path) -> Path:
    return run_dir / "request.json"


def _lock_path(run_dir: Path) -> Path:
    return run_dir / ".run.lock"


def _delete_request_path(run_dir: Path) -> Path:
    return run_dir / _DELETE_REQUEST_MARKER


def _delete_requested(run_dir: Path) -> bool:
    return _delete_request_path(run_dir).exists()


def _raise_if_delete_requested(run_dir: Path, stage_name: str | None = None) -> None:
    if not _delete_requested(run_dir):
        return
    suffix = f" during {stage_name}" if stage_name else ""
    raise RunDeletionRequested(f"Deletion requested{suffix}.")


def _delete_upload_directories(request: RunRequest) -> None:
    uploads_root_path = uploads_root().resolve()
    seen: set[Path] = set()
    for item in request.input_items:
        if str(item.source_kind or "").lower() != "upload" or not item.uploaded_path:
            continue
        try:
            directory = Path(item.uploaded_path).resolve().parent
            directory.relative_to(uploads_root_path)
        except Exception:
            continue
        if directory == uploads_root_path or directory in seen:
            continue
        shutil.rmtree(directory, ignore_errors=True)
        seen.add(directory)


def _prune_catalog_rows(request: RunRequest | None, run_dir: Path) -> None:
    if request is None or not request.output_root_path:
        return
    path = catalog_path(Path(request.output_root_path))
    if not path.exists():
        return

    target_run_id = str(request.run_id or run_dir.name)
    target_run_dir = os.path.normcase(os.path.normpath(str(run_dir.resolve())))
    kept_lines: list[str] = []
    removed_any = False

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            kept_lines.append(line)
            continue

        row_run_id = str(row.get("run_id") or "")
        row_run_dir = str(row.get("run_dir") or "")
        normalized_row_run_dir = ""
        if row_run_dir:
            try:
                normalized_row_run_dir = os.path.normcase(os.path.normpath(str(Path(row_run_dir).resolve())))
            except Exception:
                normalized_row_run_dir = os.path.normcase(os.path.normpath(row_run_dir))
        same_run = bool(target_run_id) and row_run_id.lower() == target_run_id.lower()
        same_run_dir = bool(normalized_row_run_dir) and normalized_row_run_dir == target_run_dir
        if same_run or same_run_dir:
            removed_any = True
            continue
        kept_lines.append(line)

    if not removed_any:
        return
    if kept_lines:
        path.write_text("\n".join(kept_lines) + "\n", encoding="utf-8")
        return

    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def _delete_run_dir(run_dir: Path, request: RunRequest | None = None) -> None:
    if request is not None:
        _prune_catalog_rows(request, run_dir)
        _delete_upload_directories(request)
    shutil.rmtree(run_dir, ignore_errors=True)


def _remove_obsolete_media_artifacts(media_dir: Path) -> None:
    for relative_path in ("source", "segments", "ai-raw", ".work", "timeline"):
        shutil.rmtree(media_dir / relative_path, ignore_errors=True)
    for relative_path in (
        "source.json",
        "artifacts.json",
        "README.md",
    ):
        (media_dir / relative_path).unlink(missing_ok=True)


def _resolve_duplicate_artifact_path(duplicate: dict[str, Any] | None) -> Path | None:
    if not duplicate:
        return None

    timeline_path = duplicate.get("timeline_path")
    if timeline_path:
        candidate = Path(str(timeline_path))
        if candidate.exists():
            return candidate
    artifact_path = duplicate.get("artifact_path")
    if artifact_path:
        candidate = Path(str(artifact_path))
        if candidate.exists():
            return candidate
    item_dir = duplicate.get("item_dir") or duplicate.get("media_dir")
    if item_dir:
        for relative_path in (
            ("timeline.json",),
        ):
            candidate = Path(str(item_dir)).joinpath(*relative_path)
            if candidate.exists():
                return candidate

    run_dir = duplicate.get("run_dir")
    media_id = duplicate.get("audio_id") or duplicate.get("media_id")
    if run_dir and media_id:
        media_dir = Path(str(run_dir)) / "media" / str(media_id)
        for relative_path in (
            ("timeline.json",),
        ):
            candidate = media_dir.joinpath(*relative_path)
            if candidate.exists():
                return candidate

    return None


def _load_request(run_dir: Path) -> RunRequest:
    return RunRequest.from_dict(read_json(_request_path(run_dir)))


def _load_status(run_dir: Path) -> RunStatus:
    path = _status_path(run_dir)
    if not path.exists():
        return RunStatus(run_id=run_dir.name, updated_at=now_iso())
    return RunStatus.from_dict(read_json(path))


def _write_status(run_dir: Path, status: RunStatus) -> None:
    status.updated_at = now_iso()
    write_json_atomic(_status_path(run_dir), status.to_dict())


def _write_result(run_dir: Path, result: RunResult) -> None:
    write_json_atomic(_result_path(run_dir), result.to_dict())


def _load_result(run_dir: Path) -> RunResult:
    path = _result_path(run_dir)
    if path.exists():
        return RunResult.from_dict(read_json(path))
    return RunResult(run_id=run_dir.name, run_dir=str(run_dir))


def _write_manifest(run_dir: Path, run_id: str, items: list[ManifestItem]) -> None:
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": now_iso(),
        "items": [item.to_dict() for item in items],
    }
    write_json_atomic(_manifest_path(run_dir), payload)


def _write_run_performance_summary(
    *,
    run_dir: Path,
    request: RunRequest,
    status: RunStatus,
    manifest_items: list[ManifestItem],
    run_wall_seconds: float,
) -> None:
    stage_totals: dict[str, float] = {}
    stage_max: dict[str, float] = {}
    processed_items = [
        item for item in manifest_items if str(item.status or "").lower() == "completed"
    ]
    for item in processed_items:
        for name, value in dict(item.stage_elapsed_seconds or {}).items():
            elapsed = max(0.0, float(value or 0.0))
            stage_totals[name] = round(stage_totals.get(name, 0.0) + elapsed, 3)
            stage_max[name] = max(stage_max.get(name, 0.0), elapsed)

    completed_duration = sum(max(0.0, float(item.duration_seconds or 0.0)) for item in processed_items)
    throughput = None
    if run_wall_seconds > 0 and completed_duration > 0:
        throughput = round(completed_duration / run_wall_seconds, 3)

    stage_summary = {
        name: {
            "total_wall_seconds": round(total, 3),
            "average_wall_seconds": round(total / max(1, len(processed_items)), 3),
            "max_wall_seconds": round(stage_max.get(name, 0.0), 3),
        }
        for name, total in sorted(stage_totals.items())
    }
    payload = {
        "schema_version": 1,
        "run_id": request.run_id,
        "generated_at": now_iso(),
        "compute_mode": request.compute_mode,
        "item_counts": {
            "total": status.items_total,
            "completed": status.items_done,
            "skipped": status.items_skipped,
            "failed": status.items_failed,
        },
        "duration_seconds": {
            "total_audio": round(float(status.total_duration_sec or 0.0), 3),
            "processed_audio": round(float(status.processed_duration_sec or 0.0), 3),
            "completed_audio": round(completed_duration, 3),
            "run_wall": round(max(0.0, run_wall_seconds), 3),
        },
        "throughput": {
            "completed_audio_seconds_per_wall_second": throughput,
        },
        "stages": stage_summary,
    }
    write_json_atomic(run_dir / "RUN_PERFORMANCE.json", payload)


def _preflight_skip_warning_text(status: str, count: int) -> str | None:
    if count <= 0:
        return None
    if status == "skipped_invalid":
        return f"preflight: skipped {count} invalid audio file(s)."
    if status == "skipped_too_short":
        return (
            f"preflight: skipped {count} audio file(s) shorter than "
            f"{_MIN_PREPROCESS_DURATION_SEC:.1f}s."
        )
    return None


def _acquire_run_lock(run_dir: Path) -> bool:
    lock_path = _lock_path(run_dir)
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if not _run_lock_is_stale(run_dir):
                return False
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "locked_at": now_iso(),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return True


def _release_run_lock(run_dir: Path) -> None:
    try:
        _lock_path(run_dir).unlink(missing_ok=True)
    except Exception:
        pass


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_lock_is_stale(run_dir: Path) -> bool:
    lock_path = _lock_path(run_dir)
    if not lock_path.exists():
        return False
    status = _load_status(run_dir)
    now = datetime.now(timezone.utc)
    if str(status.state or "").lower() != "running":
        try:
            lock_mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, timezone.utc)
        except OSError:
            return False
        return now - lock_mtime > _RUN_LOCK_STALE_AFTER
    updated_at = _parse_iso_timestamp(status.updated_at or status.started_at)
    if updated_at is None:
        try:
            lock_mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, timezone.utc)
        except OSError:
            return False
        return now - lock_mtime > _RUN_LOCK_STALE_AFTER
    return now - updated_at > _RUN_LOCK_STALE_AFTER


def _estimate_remaining(
    total_duration_sec: float, processed_duration_sec: float, elapsed_sec: float
) -> float | None:
    if total_duration_sec <= 0 or processed_duration_sec <= 0 or elapsed_sec <= 0:
        return None
    rate = processed_duration_sec / elapsed_sec
    if rate <= 0:
        return None
    return max(0.0, (total_duration_sec - processed_duration_sec) / rate)


def _estimate_remaining_with_history(
    *,
    predictor: Any,
    manifest_items: list[ManifestItem],
    legacy_remaining_sec: float | None,
    current_item_index: int | None = None,
    current_item_elapsed_sec: float = 0.0,
    current_stage_name: str | None = None,
    current_stage_elapsed_sec: float = 0.0,
    include_export_stage: bool = True,
) -> float | None:
    return estimate_remaining_seconds(
        predictor=predictor,
        manifest_items=manifest_items,
        legacy_remaining_sec=legacy_remaining_sec,
        current_item_index=current_item_index,
        current_item_elapsed_sec=current_item_elapsed_sec,
        current_stage_name=current_stage_name,
        current_stage_elapsed_sec=current_stage_elapsed_sec,
        include_export_stage=include_export_stage,
    )


def _write_support_docs(run_dir: Path, request: RunRequest) -> None:
    vad_config = vad_config_for_profile(request.vad_profile)
    run_info = "\n".join(
        [
            "# Run Info",
            "",
            f"- Run ID: `{request.run_id}`",
            f"- Created At: `{request.created_at}`",
            f"- Profile: `{request.profile}`",
            f"- Compute Mode: `{request.compute_mode}`",
            f"- VAD Profile: `{request.vad_profile or ''}`",
            f"- Input Count: `{len(request.input_items)}`",
            f"- Reprocess Duplicates: `{request.reprocess_duplicates}`",
            "",
            "## Processing",
            "",
            f"- Transcription backend: `{TRANSCRIPTION_BACKEND}`",
            f"- Transcription model: `{TRANSCRIPTION_MODEL_ID}`",
            "- Transcription language: `auto`",
            f"- Diarization required: `True`",
            f"- Diarization model: `{request.diarization_model_id or ''}`",
            f"- VAD backend: `{request.vad_backend}` / `{request.vad_model_id}`",
            f"- VAD parameters: `{vad_config['vad_parameters']}`",
            f"- Pipeline version: `{request.pipeline_version}`",
            f"- Generation signature: `{request.generation_signature}`",
            "",
            "## Notes",
            "",
            "- TimelineForAudio does not interpret meaning, summarize, or rewrite transcript text.",
            "- Per-item master artifacts are `convert_info.json` and `timeline.json`.",
            "- Timestamps are mapped back to the original audio timeline.",
            "- Speaker labels are mechanical labels such as `SPEAKER_00`; identities are not inferred.",
            "",
            "This run uses file-based coordination between command-created run files and the Python worker.",
            "",
        ]
    )
    notice = "\n".join(
        [
            "# Notice",
            "",
            "- This run is optimized for local processing, not cloud text generation.",
            "- Model downloads may happen on first use and are cached afterward.",
            "- Speaker diarization is required. If pyannote prerequisites are missing, the item fails instead of producing fallback speaker labels.",
            "- Timeline timestamps are based on the original audio time.",
            "",
        ]
    )
    write_text(run_dir / "RUN_INFO.md", run_info)
    write_text(run_dir / "NOTICE.md", notice)


def _resolve_input_path(item: Any) -> Path:
    if item.uploaded_path:
        return configured_path(str(item.uploaded_path))
    return configured_path(str(item.original_path))


def _parse_filename_recorded_at(path: Path) -> datetime | None:
    text = path.stem
    candidates = [
        match.group(0)
        for match in re.finditer(
            r"\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2}|\d{8}-?\d{6}",
            text,
        )
    ]
    for candidate in candidates:
        normalized = candidate.replace("_", " ")
        patterns = (
            "%Y-%m-%d %H-%M-%S",
            "%Y%m%d-%H%M%S",
            "%Y%m%d%H%M%S",
        )
        for pattern in patterns:
            try:
                return datetime.strptime(normalized, pattern)
            except ValueError:
                continue
    return None


def _process_one_item(
    *,
    run_dir: Path,
    request: RunRequest,
    item: Any,
    manifest_item: ManifestItem,
    on_stage: Callable[[str, str], None] | None = None,
    ensure_not_delete_requested: Callable[[str | None], None] | None = None,
) -> list[str]:
    source_path = _resolve_input_path(item)
    media_dir = ensure_dir(Path(request.output_root_path) / str(manifest_item.media_id))
    _remove_obsolete_media_artifacts(media_dir)
    work_dir = ensure_dir(run_dir / "work" / str(manifest_item.media_id))

    normalized_audio_path = work_dir / "audio-normalized.wav"
    speech_candidate_audio_path = work_dir / "speech-candidates.wav"

    try:
        if on_stage:
            on_stage("extract_audio", "Normalizing source audio.")
        extract_audio(source_path, normalized_audio_path)
        if ensure_not_delete_requested:
            ensure_not_delete_requested("extract_audio")

        source_record = _source_record_payload(
            source_path=source_path,
            item=item,
            manifest_item=manifest_item,
        )

        if on_stage:
            on_stage("detect_speech_candidates", "Detecting speech candidates.")
        vad_parameters = vad_config_for_profile(request.vad_profile)["vad_parameters"]
        cut_map = trim_audio(
            normalized_audio_path,
            speech_candidate_audio_path,
            manifest_item.duration_seconds,
            min_silence_duration_ms=int(vad_parameters.get("min_silence_duration_ms", 500)),
            write_audio=False,
        )
        if ensure_not_delete_requested:
            ensure_not_delete_requested("detect_speech_candidates")

        if on_stage:
            on_stage("diarize_audio", "Running required speaker diarization.")
        speaker_payload = generate_speaker_turns(
            source_name=item.display_name,
            audio_path=normalized_audio_path,
            compute_mode=request.compute_mode,
        )
        if ensure_not_delete_requested:
            ensure_not_delete_requested("diarize_audio")

        speaker_labels = {
            str(turn.get("speaker") or "").strip()
            for turn in speaker_payload.get("turns", [])
            if str(turn.get("speaker") or "").strip()
        }
        if not speaker_labels:
            raise RuntimeError("Speaker diarization produced no speaker turns.")
        manifest_item.speaker_count = len(speaker_labels) or None
        manifest_item.speaker_count_status = "confirmed" if speaker_labels else "unavailable"
        manifest_item.speaker_count_note = (
            None if speaker_labels else "No speaker turns were available."
        )

        if on_stage:
            on_stage("transcribe_audio", "Transcribing speech with Whisper.")
        transcription_result = generate_transcript_segments(
            audio_path=normalized_audio_path,
            compute_mode=request.compute_mode,
        )
        raw_transcript_segment_rows = [
            {
                "index": segment.index,
                "start_sec": segment.start,
                "end_sec": segment.end,
                "text": segment.text,
                "avg_logprob": segment.avg_logprob,
                "no_speech_probability": segment.no_speech_probability,
            }
            for segment in transcription_result.segments
        ]
        transcript_segment_rows, rejected_transcript_segment_rows = _validate_transcript_segments(
            raw_transcript_segment_rows,
            cut_map,
            list(speaker_payload.get("turns") or []),
        )
        transcription_warnings = list(transcription_result.warnings)
        if rejected_transcript_segment_rows:
            transcription_warnings.append(
                f"Speech transcript validation rejected {len(rejected_transcript_segment_rows)} segment(s)."
            )
        transcription_payload = {
            "schema_version": 1,
            "backend": transcription_result.backend_name,
            "model_id": transcription_result.model_id,
            "status": transcription_result.status,
            "device": transcription_result.device,
            "compute_type": transcription_result.compute_type,
            "language": transcription_result.language,
            "language_probability": transcription_result.language_probability,
            "duration": transcription_result.duration,
            "warning_count": len(transcription_warnings),
            "warnings": transcription_warnings,
            "raw_segment_count": len(raw_transcript_segment_rows),
            "segment_count": len(transcript_segment_rows),
            "rejected_segment_count": len(rejected_transcript_segment_rows),
            "raw_segments": raw_transcript_segment_rows,
            "segments": transcript_segment_rows,
            "rejected_segments": rejected_transcript_segment_rows,
        }
        if transcription_result.status != "ok":
            raise RuntimeError(
                "; ".join(transcription_result.warnings) or "Speech transcription failed."
            )
        if ensure_not_delete_requested:
            ensure_not_delete_requested("transcribe_audio")

        if on_stage:
            on_stage("generate_artifacts", "Writing final timeline artifacts.")
        timeline_payload = _build_speaker_transcript_timeline(
            source_record=source_record,
            speaker_payload=speaker_payload,
            transcription_payload=transcription_payload,
            conversion_signature=request.generation_signature,
            pipeline_version=request.pipeline_version,
        )
        conversion_info_payload = _build_conversion_info_payload(
            request=request,
            source_record=source_record,
            cut_map=cut_map,
            speaker_payload=speaker_payload,
            transcription_payload=transcription_payload,
        )
        timeline_json_path = media_dir / "timeline.json"
        conversion_info_path = media_dir / "convert_info.json"
        write_json_atomic(timeline_json_path, timeline_payload)
        write_json_atomic(conversion_info_path, conversion_info_payload)
        if ensure_not_delete_requested:
            ensure_not_delete_requested("generate_artifacts")
        return [
            *list(speaker_payload.get("warnings") or []),
            *transcription_warnings,
        ]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _recorded_at_metadata(source_path: Path, manifest_item: ManifestItem) -> dict[str, Any]:
    captured_at = str(getattr(manifest_item, "captured_at", None) or "").strip()
    if captured_at:
        return {
            "recorded_at": captured_at,
            "recorded_at_source": "metadata",
            "recorded_at_timezone": "UTC",
        }
    parsed = _parse_filename_recorded_at(source_path)
    if parsed is not None:
        localized = parsed.replace(tzinfo=timezone(timedelta(hours=9)))
        return {
            "recorded_at": localized.isoformat(),
            "recorded_at_source": "filename",
            "recorded_at_timezone": "Asia/Tokyo",
        }
    return {
        "recorded_at": None,
        "recorded_at_source": "unknown",
        "recorded_at_timezone": None,
    }


def _absolute_at(recorded_at: str | None, offset_seconds: float) -> str | None:
    if not recorded_at:
        return None
    try:
        base = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (base + timedelta(seconds=float(offset_seconds or 0.0))).isoformat()


def _source_record_payload(
    *,
    source_path: Path,
    item: Any,
    manifest_item: ManifestItem,
) -> dict[str, Any]:
    recorded_at = _recorded_at_metadata(source_path, manifest_item)
    return {
        "schema_version": 1,
        "file_name": source_path.name,
        "display_name": item.display_name,
        "original_path": item.original_path,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "source_relative_path": getattr(item, "source_relative_path", None),
        "source_file_identity": getattr(item, "source_file_identity", None),
        "source_hash": manifest_item.source_hash,
        "size_bytes": manifest_item.size_bytes,
        "duration_sec": manifest_item.duration_seconds,
        "container_name": getattr(manifest_item, "container_name", None),
        "extension": getattr(manifest_item, "extension", None),
        "audio_codec": getattr(manifest_item, "audio_codec", None),
        "audio_channels": getattr(manifest_item, "audio_channels", None),
        "audio_sample_rate": getattr(manifest_item, "audio_sample_rate", None),
        "bitrate": getattr(manifest_item, "bitrate", None),
        **recorded_at,
    }


def _build_conversion_info_payload(
    *,
    request: RunRequest,
    source_record: dict[str, Any],
    cut_map: list[dict[str, float]],
    speaker_payload: dict[str, Any],
    transcription_payload: dict[str, Any],
) -> dict[str, Any]:
    vad_config = vad_config_for_profile(request.vad_profile)
    return {
        "schema_version": 1,
        "artifact_type": "convert_info",
        "application": "TimelineForAudio",
        "generated_at": now_iso(),
        "source": source_record,
        "pipeline": {
            "pipeline_version": request.pipeline_version,
            "generation_signature": request.generation_signature,
            "compute_mode": request.compute_mode,
            "speech_activity_detection": {
                "backend": request.vad_backend,
                "model_id": request.vad_model_id,
                "profile": vad_config["profile"],
                "parameters": vad_config["vad_parameters"],
            },
            "speaker_diarization": {
                "required": True,
                "backend": speaker_payload.get("backend"),
                "model_id": speaker_payload.get("model_id"),
                "status": speaker_payload.get("status"),
                "turn_count": speaker_payload.get("turn_count"),
                "warning_count": speaker_payload.get("warning_count"),
            },
            "speech_transcription": {
                "backend": transcription_payload.get("backend"),
                "model_id": transcription_payload.get("model_id"),
                "status": transcription_payload.get("status"),
                "language": transcription_payload.get("language"),
                "language_probability": transcription_payload.get("language_probability"),
                "device": transcription_payload.get("device"),
                "compute_type": transcription_payload.get("compute_type"),
                "raw_segment_count": transcription_payload.get("raw_segment_count"),
                "segment_count": transcription_payload.get("segment_count"),
                "rejected_segment_count": transcription_payload.get("rejected_segment_count"),
                "warning_count": transcription_payload.get("warning_count"),
            },
        },
        "processing_flow": [
            {
                "step": 1,
                "name": "audio_normalization",
                "description": "Decode source audio into the worker's analysis format.",
                "persistent_output": False,
            },
            {
                "step": 2,
                "name": "speech_activity_detection",
                "description": "Find source-audio ranges that are likely to contain speech.",
                "persistent_output": False,
            },
            {
                "step": 3,
                "name": "speaker_diarization",
                "description": "Assign mechanical speaker labels to source-audio time ranges.",
                "persistent_output": False,
            },
            {
                "step": 4,
                "name": "speech_transcription",
                "description": "Transcribe source audio with Whisper automatic language detection.",
                "persistent_output": False,
            },
            {
                "step": 5,
                "name": "timeline_merge",
                "description": "Merge speaker labels, timestamps, and validated Whisper transcript text into the final timeline JSON without rewriting accepted text.",
                "persistent_output": True,
            },
        ],
        "counts": {
            "speech_candidate_ranges": len(cut_map),
            "speaker_turns": len(speaker_payload.get("turns") or []),
            "raw_transcript_segments": len(transcription_payload.get("raw_segments") or []),
            "transcript_segments": len(transcription_payload.get("segments") or []),
            "rejected_transcript_segments": len(transcription_payload.get("rejected_segments") or []),
        },
        "output_files": {
            "convert_info": "convert_info.json",
            "timeline": "timeline.json",
        },
    }


def _validate_transcript_segments(
    raw_segments: list[dict[str, Any]],
    speech_candidates: list[dict[str, Any]],
    speaker_turns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    repeated_texts = {
        text
        for text, count in Counter(
            _normalize_transcript_text(str(segment.get("text") or "")) for segment in raw_segments
        ).items()
        if text and count >= 3
    }
    known_hallucinations = {
        _normalize_transcript_text(phrase) for phrase in _KNOWN_SILENCE_HALLUCINATION_PHRASES
    }

    for segment in raw_segments:
        start = float(segment.get("start_sec", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("end_sec", segment.get("end", start)) or start)
        text = str(segment.get("text") or "").strip()
        normalized_text = _normalize_transcript_text(text)
        speech_overlap = _interval_overlap_with_speech_candidates(start, end, speech_candidates)
        speaker = best_speaker_for_interval(start, end, speaker_turns)
        avg_logprob = _optional_float(segment.get("avg_logprob"))
        no_speech_probability = _optional_float(segment.get("no_speech_probability"))

        reject = False
        reasons: list[str] = []
        if speech_overlap < _MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC:
            reasons.append("no_speech_candidate_overlap")
            reject = True
        if not speaker:
            reasons.append("no_speaker_overlap")
        if avg_logprob is not None and avg_logprob < _LOW_TRANSCRIPT_CONFIDENCE:
            reasons.append("low_confidence")
        if no_speech_probability is not None and no_speech_probability >= _HIGH_NO_SPEECH_PROBABILITY:
            reasons.append("high_no_speech_probability")
            reject = True
        if (
            normalized_text in known_hallucinations
            and normalized_text in repeated_texts
            and (speech_overlap < _MIN_TRANSCRIPT_SPEECH_OVERLAP_SEC or not speaker)
        ):
            reasons.append("known_silence_hallucination_phrase")
            reasons.append("repeated_hallucination_phrase")
            reject = True

        enriched = dict(segment)
        enriched["validation"] = {
            "state": "rejected" if reject else "validated",
            "speech_overlap_sec": round(speech_overlap, 3),
            "speaker": speaker,
            "reasons": reasons,
        }
        if reject:
            enriched["rejection_reasons"] = reasons
            rejected.append(enriched)
        else:
            validated.append(enriched)

    return validated, rejected


def _normalize_transcript_text(value: str) -> str:
    return "".join(str(value or "").split()).casefold()


def _interval_overlap_with_speech_candidates(
    start: float,
    end: float,
    speech_candidates: list[dict[str, Any]],
) -> float:
    if end <= start:
        return 0.0
    overlap = 0.0
    for candidate in speech_candidates:
        candidate_start = float(candidate.get("original_start", candidate.get("startSec", 0.0)) or 0.0)
        candidate_end = float(candidate.get("original_end", candidate.get("endSec", candidate_start)) or candidate_start)
        overlap += max(0.0, min(end, candidate_end) - max(start, candidate_start))
    return overlap


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_speaker_transcript_timeline(
    *,
    source_record: dict[str, Any],
    speaker_payload: dict[str, Any],
    transcription_payload: dict[str, Any],
    conversion_signature: str,
    pipeline_version: str,
) -> dict[str, Any]:
    recorded_at = source_record.get("recorded_at")
    speaker_turns = list(speaker_payload.get("turns") or [])
    raw_segments = list(transcription_payload.get("segments") or [])
    turns: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments, start=1):
        start = float(segment.get("start_sec", segment.get("start", 0.0)) or 0.0)
        end = float(segment.get("end_sec", segment.get("end", start)) or start)
        speaker = best_speaker_for_interval(start, end, speaker_turns)
        turns.append(
            {
                "index": index,
                "start_sec": start,
                "end_sec": end,
                "absolute_start_at": _absolute_at(recorded_at, start),
                "absolute_end_at": _absolute_at(recorded_at, end),
                "speaker": speaker,
                "text": str(segment.get("text") or ""),
                "transcription_segment_index": segment.get("index"),
                "avg_logprob": segment.get("avg_logprob"),
                "no_speech_probability": segment.get("no_speech_probability"),
            }
        )
    source_text = "".join(str(segment.get("text") or "") for segment in raw_segments)
    timeline_text = "".join(str(turn.get("text") or "") for turn in turns)
    if source_text != timeline_text:
        raise RuntimeError("Transcript text was changed while assigning speakers.")
    return {
        "schema_version": 1,
        "artifact_type": "timeline",
        "source": source_record,
        "pipeline": {
            "pipeline_version": pipeline_version,
            "generation_signature": conversion_signature,
            "speaker_backend": speaker_payload.get("backend"),
            "speaker_model_id": speaker_payload.get("model_id"),
            "transcription_backend": transcription_payload.get("backend"),
            "transcription_model_id": transcription_payload.get("model_id"),
            "transcription_language": transcription_payload.get("language"),
            "transcription_device": transcription_payload.get("device"),
            "transcription_compute_type": transcription_payload.get("compute_type"),
            "raw_transcript_segments": transcription_payload.get("raw_segment_count"),
            "rejected_transcript_segments": transcription_payload.get("rejected_segment_count"),
        },
        "turn_count": len(turns),
        "turns": turns,
    }


def _run_sources_accessible(run_dir: Path) -> bool:
    try:
        request = _load_request(run_dir)
    except Exception:
        return False
    return all(_resolve_input_path(item).exists() for item in request.input_items)


def _make_media_id(item: Any, file_hash: str) -> str:
    stem = slugify(Path(item.display_name or Path(item.original_path).stem).stem)
    identity = str(getattr(item, "source_file_identity", "") or "").strip()
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8] if identity else file_hash[:8]
    return f"{stem}-{suffix or short_id()}"


def _collect_pending_runs() -> list[Path]:
    return _collect_runs_by_state("pending")


def _collect_running_runs() -> list[Path]:
    return _collect_runs_by_state("running")


def _running_run_is_active(run_dir: Path) -> bool:
    return _lock_path(run_dir).exists() and not _run_lock_is_stale(run_dir)


def _mark_interrupted_running_run(run_dir: Path) -> bool:
    status = _load_status(run_dir)
    if str(status.state or "").lower() != "running":
        return False
    if _running_run_is_active(run_dir):
        return False

    status.state = "canceled"
    status.current_stage = "interrupted"
    status.message = _INTERRUPTED_RUN_MESSAGE
    status.estimated_remaining_sec = None
    status.completed_at = now_iso()
    if _INTERRUPTED_RUN_MESSAGE not in status.warnings:
        status.warnings.append(_INTERRUPTED_RUN_MESSAGE)
    _write_status(run_dir, status)

    result = _load_result(run_dir)
    result.run_id = result.run_id or status.run_id or run_dir.name
    result.state = "canceled"
    result.run_dir = result.run_dir or str(run_dir)
    if _INTERRUPTED_RUN_MESSAGE not in result.warnings:
        result.warnings.append(_INTERRUPTED_RUN_MESSAGE)
    _write_result(run_dir, result)

    append_log(_run_log_path(run_dir), f"[{now_iso()}] {_INTERRUPTED_RUN_MESSAGE}")
    _release_run_lock(run_dir)
    return True


def _retire_interrupted_running_runs() -> bool:
    has_active_running_run = False
    for candidate in _collect_running_runs():
        if _running_run_is_active(candidate):
            has_active_running_run = True
            continue
        _mark_interrupted_running_run(candidate)
    return has_active_running_run


def _collect_runs_by_state(*states: str) -> list[Path]:
    target_states = {state.lower() for state in states}
    settings = load_settings()
    rows: list[Path] = []
    root = settings.get("outputRoot")
    root_text = root.strip() if isinstance(root, str) else ""
    if not root_text:
        return rows
    root_path = configured_path(root_text)
    if not root_path.exists():
        return rows
    run_dirs = list(_runtime_runs_root(root_path).glob("run-*"))
    run_dirs.extend(root_path.glob("run-*"))
    for candidate in sorted({item.resolve(): item for item in run_dirs}.values()):
        if not candidate.is_dir():
            continue
        if _delete_requested(candidate):
            continue
        if not _request_path(candidate).exists():
            continue
        status = _load_status(candidate)
        if status.state.lower() in target_states:
            rows.append(candidate)
    return rows

def process_run(run_dir: Path | None = None) -> bool:
    lock_acquired = False
    delete_requested = False
    if run_dir is None:
        if _retire_interrupted_running_runs():
            return False
        pending = _collect_pending_runs()
        if not pending:
            return False
        run_dir = None
        for candidate in pending:
            if not _run_sources_accessible(candidate):
                continue
            if not _acquire_run_lock(candidate):
                continue
            run_dir = candidate
            lock_acquired = True
            break
        if run_dir is None:
            return False

    run_dir = run_dir.resolve()
    if not _request_path(run_dir).exists():
        return False
    status_before_lock = _load_status(run_dir)
    if str(status_before_lock.state or "").lower() == "running":
        _mark_interrupted_running_run(run_dir)
        return False
    if not lock_acquired and not _acquire_run_lock(run_dir):
        return False
    lock_acquired = True

    log_path = _run_log_path(run_dir)
    request = _load_request(run_dir)
    assert_runtime_supports_compute_mode(request.compute_mode)
    _raise_if_delete_requested(run_dir, "queued")
    _write_support_docs(run_dir, request)
    status = RunStatus(
        run_id=request.run_id,
        state="running",
        current_stage="preflight",
        message="Preparing run.",
        items_total=len(request.input_items),
        progress_percent=1.0 if request.input_items else 0.0,
        started_at=now_iso(),
    )
    result = RunResult(
        run_id=request.run_id,
        state="running",
        run_dir=str(run_dir),
        output_root_id=request.output_root_id,
        output_root_path=request.output_root_path,
    )
    warnings: list[str] = []
    compute_mode = str(request.compute_mode or "cpu").lower()
    started = monotonic()
    catalog = load_catalog(Path(request.output_root_path))
    manifest_items: list[ManifestItem] = []
    appended_catalog_rows: list[dict[str, Any]] = []
    preflight_skip_counts: Counter[str] = Counter()

    def ensure_not_delete_requested(stage_name: str | None = None) -> None:
        _raise_if_delete_requested(run_dir, stage_name)

    try:
        _write_status(run_dir, status)
        _write_result(run_dir, result)
        append_log(log_path, f"[{now_iso()}] Starting run {request.run_id}")
        for index, input_item in enumerate(request.input_items, start=1):
            _raise_if_delete_requested(run_dir, "preflight")
            status.current_item = input_item.display_name
            status.message = (
                f"Preflight {index}/{len(request.input_items)}: {input_item.display_name}"
            )
            status.progress_percent = overall_progress_percent(
                processed_duration_sec=0.0,
                total_duration_sec=0.0,
                current_stage="preflight",
                current_stage_elapsed_sec=0.0,
                current_item_duration_sec=0.0,
                compute_mode=compute_mode,
                preflight_fraction=index / max(len(request.input_items), 1),
                total_items=max(len(request.input_items), 1),
            )
            _write_status(run_dir, status)
            source_path = _resolve_input_path(input_item)
            try:
                file_hash = sha256_file(source_path)
                media_probe = probe_audio(source_path)
            except Exception as exc:
                fallback_hash = f"preflight-{short_id()}"
                append_log(
                    log_path,
                    f"[{now_iso()}] Preflight failed: {input_item.original_path}",
                )
                append_log(log_path, traceback.format_exc())
                manifest_items.append(
                    ManifestItem(
                        input_id=input_item.input_id,
                        source_kind=input_item.source_kind,
                        original_path=input_item.original_path,
                        file_name=Path(input_item.original_path).name,
                        size_bytes=input_item.size_bytes,
                        duration_seconds=0.0,
                        source_hash=fallback_hash,
                        conversion_signature=request.conversion_signature,
                        duplicate_status="new",
                        audio_id=_make_media_id(input_item, fallback_hash),
                        status="skipped_invalid",
                        source_id=input_item.source_id,
                        source_relative_path=input_item.source_relative_path,
                        source_file_identity=input_item.source_file_identity,
                        extension=source_path.suffix.lstrip(".").lower() or None,
                        diarization_enabled=request.diarization_enabled,
                        model_id=request.transcription_model_id,
                        model_version=request.transcription_model_id,
                        pipeline_version=request.pipeline_version,
                    )
                )
                preflight_skip_counts["skipped_invalid"] += 1
                status.items_skipped += 1
                _write_manifest(run_dir, request.run_id, manifest_items)
                _write_status(run_dir, status)
                continue
            media_duration_seconds = float(media_probe["duration_seconds"])
            if media_duration_seconds < _MIN_PREPROCESS_DURATION_SEC:
                append_log(
                    log_path,
                    f"[{now_iso()}] Preflight skipped as too short: "
                    f"{input_item.original_path} ({media_duration_seconds:.3f}s)",
                )
                manifest_items.append(
                    ManifestItem(
                        input_id=input_item.input_id,
                        source_kind=input_item.source_kind,
                        original_path=input_item.original_path,
                        file_name=Path(input_item.original_path).name,
                        size_bytes=int(media_probe["size_bytes"]),
                        duration_seconds=media_duration_seconds,
                        source_hash=file_hash,
                        conversion_signature=request.conversion_signature,
                        duplicate_status="new",
                        audio_id=_make_media_id(input_item, file_hash),
                        status="skipped_too_short",
                        source_id=input_item.source_id,
                        source_relative_path=input_item.source_relative_path,
                        source_file_identity=input_item.source_file_identity,
                        container_name=media_probe.get("container_name"),
                        extension=media_probe.get("extension"),
                        audio_codec=media_probe.get("audio_codec"),
                        audio_channels=media_probe.get("audio_channels"),
                        audio_sample_rate=media_probe.get("audio_sample_rate"),
                        bitrate=media_probe.get("bitrate"),
                        diarization_enabled=request.diarization_enabled,
                        model_id=request.transcription_model_id,
                        model_version=request.transcription_model_id,
                        pipeline_version=request.pipeline_version,
                        captured_at=media_probe.get("captured_at"),
                    )
                )
                preflight_skip_counts["skipped_too_short"] += 1
                status.items_skipped += 1
                _write_manifest(run_dir, request.run_id, manifest_items)
                _write_status(run_dir, status)
                continue
            duplicate = catalog.get(
                catalog_key(
                    file_hash,
                    request.conversion_signature,
                    input_item.source_file_identity,
                )
            )
            duplicate_status = "new"
            duplicate_of = None
            duplicate_artifact_path = _resolve_duplicate_artifact_path(duplicate)
            if duplicate_artifact_path is not None:
                duplicate_of = str(
                    duplicate.get("audio_id")
                    or duplicate.get("media_id")
                    or duplicate_artifact_path
                    or duplicate.get("run_dir")
                    or ""
                )
                duplicate_status = (
                    "duplicate_reprocess" if request.reprocess_duplicates else "duplicate_skip"
                )
            elif duplicate:
                append_log(
                    log_path,
                    f"[{now_iso()}] Duplicate catalog entry is stale. Processing again: {input_item.original_path}",
                )

            manifest_items.append(
                ManifestItem(
                    input_id=input_item.input_id,
                    source_kind=input_item.source_kind,
                    original_path=input_item.original_path,
                    file_name=Path(input_item.original_path).name,
                    size_bytes=int(media_probe["size_bytes"]),
                    duration_seconds=media_duration_seconds,
                    source_hash=file_hash,
                    conversion_signature=request.conversion_signature,
                    duplicate_status=duplicate_status,
                    duplicate_of=duplicate_of or None,
                    audio_id=_make_media_id(input_item, file_hash),
                    status="queued",
                    source_id=input_item.source_id,
                    source_relative_path=input_item.source_relative_path,
                    source_file_identity=input_item.source_file_identity,
                    container_name=media_probe.get("container_name"),
                    extension=media_probe.get("extension"),
                    audio_codec=media_probe.get("audio_codec"),
                    audio_channels=media_probe.get("audio_channels"),
                    audio_sample_rate=media_probe.get("audio_sample_rate"),
                    bitrate=media_probe.get("bitrate"),
                    diarization_enabled=request.diarization_enabled,
                    model_id=request.transcription_model_id,
                    model_version=request.transcription_model_id,
                    pipeline_version=request.pipeline_version,
                    captured_at=media_probe.get("captured_at"),
                )
            )

        total_duration = sum(item.duration_seconds for item in manifest_items)
        for skip_status, count in sorted(preflight_skip_counts.items()):
            warning_text = _preflight_skip_warning_text(skip_status, count)
            if warning_text:
                warnings.append(warning_text)
        status.items_total = len(manifest_items)
        status.total_duration_sec = round(total_duration, 3)
        status.current_item = None
        status.message = "Preflight completed."
        status.progress_percent = 5.0 if manifest_items else 0.0
        _write_manifest(run_dir, request.run_id, manifest_items)
        _write_status(run_dir, status)
        append_log(log_path, f"[{now_iso()}] Preflight complete for {len(manifest_items)} item(s).")
        eta_predictor = build_eta_predictor(
            output_root=Path(request.output_root_path),
            current_run_id=request.run_id,
            compute_mode=request.compute_mode,
        )
        append_log(
            log_path,
            f"[{now_iso()}] ETA history loaded: {eta_predictor.sample_count} sample(s) "
            f"for compute_mode={request.compute_mode}.",
        )

        completed_items: list[ManifestItem] = []
        for index, (input_item, manifest_item) in enumerate(
            zip(request.input_items, manifest_items, strict=False), start=1
        ):
            _raise_if_delete_requested(run_dir, "extract_audio")
            if manifest_item.status in _PREFLIGHT_SKIPPED_STATUSES:
                append_log(
                    log_path,
                    f"[{now_iso()}] Skipped after preflight classification "
                    f"({manifest_item.status}): {input_item.original_path}",
                )
                continue
            status.current_item = input_item.display_name
            status.current_item_elapsed_sec = 0.0
            status.current_stage_elapsed_sec = 0.0
            status.current_stage = "extract_audio"
            status.message = f"Processing {index}/{len(manifest_items)}: {input_item.display_name}"
            status.progress_percent = overall_progress_percent(
                processed_duration_sec=status.processed_duration_sec,
                total_duration_sec=status.total_duration_sec,
                current_stage="extract_audio",
                current_stage_elapsed_sec=0.0,
                current_item_duration_sec=manifest_item.duration_seconds,
                compute_mode=compute_mode,
                total_items=max(len(manifest_items), 1),
                completed_items=completed_item_count(status),
            )
            _write_status(run_dir, status)

            if manifest_item.duplicate_status == "duplicate_skip":
                manifest_item.status = "skipped_duplicate"
                manifest_item.processing_wall_seconds = 0.0
                manifest_item.stage_elapsed_seconds = {}
                status.items_skipped += 1
                status.processed_duration_sec = round(
                    status.processed_duration_sec + manifest_item.duration_seconds, 3
                )
                status.current_stage_elapsed_sec = 0.0
                status.progress_percent = completed_progress_percent(
                    processed_duration_sec=status.processed_duration_sec,
                    total_duration_sec=status.total_duration_sec,
                    total_items=max(len(manifest_items), 1),
                    completed_items=completed_item_count(status),
                )
                legacy_remaining = _estimate_remaining(
                    status.total_duration_sec,
                    status.processed_duration_sec,
                    monotonic() - started,
                )
                status.estimated_remaining_sec = _estimate_remaining_with_history(
                    predictor=eta_predictor,
                    manifest_items=manifest_items,
                    legacy_remaining_sec=legacy_remaining,
                    current_item_index=None,
                    current_item_elapsed_sec=0.0,
                )
                _write_manifest(run_dir, request.run_id, manifest_items)
                _write_status(run_dir, status)
                append_log(log_path, f"[{now_iso()}] Skipped duplicate: {input_item.original_path}")
                continue

            item_started = monotonic()
            heartbeat_state = {
                "stage_name": "extract_audio",
                "stage_started_at": item_started,
                "media_duration_sec": max(1.0, manifest_item.duration_seconds),
                "stage_elapsed_seconds": {},
            }
            heartbeat_stop = threading.Event()
            heartbeat_lock = threading.Lock()

            def snapshot_stage_state(now_value: float | None = None) -> tuple[str, float, dict[str, float]]:
                reference = now_value if now_value is not None else monotonic()
                with heartbeat_lock:
                    stage_name = str(heartbeat_state["stage_name"])
                    stage_started_at = float(heartbeat_state["stage_started_at"])
                    completed_stage_seconds = {
                        str(name): float(value)
                        for name, value in dict(heartbeat_state["stage_elapsed_seconds"]).items()
                    }
                current_stage_elapsed = max(0.0, reference - stage_started_at)
                stage_elapsed_snapshot = {
                    name: round(max(0.0, value), 3)
                    for name, value in completed_stage_seconds.items()
                    if value > 0
                }
                stage_elapsed_snapshot[stage_name] = round(
                    stage_elapsed_snapshot.get(stage_name, 0.0) + current_stage_elapsed,
                    3,
                )
                return stage_name, round(current_stage_elapsed, 3), stage_elapsed_snapshot

            def heartbeat() -> None:
                while not heartbeat_stop.wait(2.0):
                    now_value = monotonic()
                    elapsed = now_value - item_started
                    stage_name, current_stage_elapsed, _ = snapshot_stage_state(now_value)
                    completed_count = completed_item_count(status)
                    current_fraction = current_item_stage_fraction(
                        stage_name,
                        current_stage_elapsed,
                        manifest_item.duration_seconds,
                        compute_mode,
                    )
                    effective_processed = status.processed_duration_sec + (
                        manifest_item.duration_seconds * current_fraction
                    )
                    status.current_item_elapsed_sec = round(elapsed, 3)
                    status.current_stage_elapsed_sec = current_stage_elapsed
                    status.progress_percent = max(
                        status.progress_percent,
                        overall_progress_percent(
                            processed_duration_sec=status.processed_duration_sec,
                            total_duration_sec=status.total_duration_sec,
                            current_stage=stage_name,
                            current_stage_elapsed_sec=current_stage_elapsed,
                            current_item_duration_sec=manifest_item.duration_seconds,
                            compute_mode=compute_mode,
                            total_items=max(len(manifest_items), 1),
                            completed_items=completed_count,
                        ),
                    )
                    legacy_remaining = _estimate_remaining(
                        status.total_duration_sec,
                        effective_processed,
                        monotonic() - started,
                    )
                    status.estimated_remaining_sec = _estimate_remaining_with_history(
                        predictor=eta_predictor,
                        manifest_items=manifest_items,
                        legacy_remaining_sec=legacy_remaining,
                        current_item_index=index - 1,
                        current_item_elapsed_sec=elapsed,
                        current_stage_name=stage_name,
                        current_stage_elapsed_sec=current_stage_elapsed,
                    )
                    _write_status(run_dir, status)

            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            heartbeat_thread.start()

            def stage_update(stage_name: str, message: str) -> None:
                _raise_if_delete_requested(run_dir, stage_name)
                now_value = monotonic()
                with heartbeat_lock:
                    previous_stage_name = str(heartbeat_state["stage_name"])
                    previous_stage_started_at = float(heartbeat_state["stage_started_at"])
                    stage_elapsed_seconds = {
                        str(name): float(value)
                        for name, value in dict(heartbeat_state["stage_elapsed_seconds"]).items()
                    }
                    if stage_name != previous_stage_name:
                        previous_stage_elapsed = max(0.0, now_value - previous_stage_started_at)
                        stage_elapsed_seconds[previous_stage_name] = round(
                            stage_elapsed_seconds.get(previous_stage_name, 0.0)
                            + previous_stage_elapsed,
                            3,
                        )
                        heartbeat_state["stage_name"] = stage_name
                        heartbeat_state["stage_started_at"] = now_value
                        heartbeat_state["stage_elapsed_seconds"] = stage_elapsed_seconds
                        current_stage_elapsed = 0.0
                    else:
                        current_stage_elapsed = round(
                            max(0.0, now_value - previous_stage_started_at),
                            3,
                        )
                elapsed = now_value - item_started
                status.current_stage = stage_name
                status.message = message
                status.current_item = input_item.display_name
                status.current_item_elapsed_sec = round(elapsed, 3)
                status.current_stage_elapsed_sec = current_stage_elapsed
                status.progress_percent = max(
                    status.progress_percent,
                    overall_progress_percent(
                        processed_duration_sec=status.processed_duration_sec,
                        total_duration_sec=status.total_duration_sec,
                        current_stage=stage_name,
                        current_stage_elapsed_sec=current_stage_elapsed,
                        current_item_duration_sec=manifest_item.duration_seconds,
                        compute_mode=compute_mode,
                        total_items=max(len(manifest_items), 1),
                        completed_items=completed_item_count(status),
                    ),
                )
                current_fraction = current_item_stage_fraction(
                    stage_name,
                    current_stage_elapsed,
                    manifest_item.duration_seconds,
                    compute_mode,
                )
                effective_processed = status.processed_duration_sec + (
                    manifest_item.duration_seconds * current_fraction
                )
                legacy_remaining = _estimate_remaining(
                    status.total_duration_sec,
                    effective_processed,
                    monotonic() - started,
                )
                status.estimated_remaining_sec = _estimate_remaining_with_history(
                    predictor=eta_predictor,
                    manifest_items=manifest_items,
                    legacy_remaining_sec=legacy_remaining,
                    current_item_index=index - 1,
                    current_item_elapsed_sec=elapsed,
                    current_stage_name=stage_name,
                    current_stage_elapsed_sec=current_stage_elapsed,
                )
                _write_status(run_dir, status)
                append_log(log_path, f"[{now_iso()}] {stage_name}: {input_item.original_path}")

            try:
                item_warnings = _process_one_item(
                    run_dir=run_dir,
                    request=request,
                    item=input_item,
                    manifest_item=manifest_item,
                    on_stage=stage_update,
                    ensure_not_delete_requested=ensure_not_delete_requested,
                )
                for warning in item_warnings:
                    warning_text = f"{input_item.display_name}: {warning}"
                    warnings.append(warning_text)
                    append_log(log_path, f"[{now_iso()}] Warning: {warning_text}")
                manifest_item.status = "completed"
                completed_items.append(manifest_item)
                appended_catalog_rows.append(
                    {
                        "run_id": request.run_id,
                        "run_dir": str(run_dir),
                        "audio_id": manifest_item.media_id,
                        "media_id": manifest_item.media_id,
                        "item_dir": str(Path(request.output_root_path) / str(manifest_item.media_id)),
                        "artifact_path": str(
                            Path(request.output_root_path)
                            / str(manifest_item.media_id)
                            / "timeline.json"
                        ),
                        "conversion_info_path": str(
                            Path(request.output_root_path)
                            / str(manifest_item.media_id)
                            / "convert_info.json"
                        ),
                        "source_hash": manifest_item.sha256,
                        "conversion_signature": manifest_item.conversion_signature,
                        "source_id": manifest_item.source_id,
                        "source_relative_path": manifest_item.source_relative_path,
                        "source_file_identity": manifest_item.source_file_identity,
                        "file_name": manifest_item.file_name,
                        "original_path": manifest_item.original_path,
                        "duration_seconds": manifest_item.duration_seconds,
                        "created_at": now_iso(),
                    }
                )
                status.items_done += 1
                append_log(log_path, f"[{now_iso()}] Completed: {input_item.original_path}")
            except RunDeletionRequested:
                raise
            except Exception as exc:
                manifest_item.status = "failed"
                status.items_failed += 1
                warnings.append(f"{input_item.display_name}: {exc}")
                append_log(log_path, f"[{now_iso()}] Failed: {input_item.original_path}")
                append_log(log_path, traceback.format_exc())
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=1.0)
                _, _, stage_elapsed_snapshot = snapshot_stage_state()
                manifest_item.processing_wall_seconds = round(monotonic() - item_started, 3)
                manifest_item.stage_elapsed_seconds = stage_elapsed_snapshot

            status.processed_duration_sec = round(
                status.processed_duration_sec + manifest_item.duration_seconds, 3
            )
            status.current_item_elapsed_sec = round(monotonic() - item_started, 3)
            status.current_stage_elapsed_sec = 0.0
            status.progress_percent = completed_progress_percent(
                processed_duration_sec=status.processed_duration_sec,
                total_duration_sec=status.total_duration_sec,
                total_items=max(len(manifest_items), 1),
                completed_items=completed_item_count(status),
            )
            legacy_remaining = _estimate_remaining(
                status.total_duration_sec,
                status.processed_duration_sec,
                monotonic() - started,
            )
            status.estimated_remaining_sec = _estimate_remaining_with_history(
                predictor=eta_predictor,
                manifest_items=manifest_items,
                legacy_remaining_sec=legacy_remaining,
                current_item_index=None,
                current_item_elapsed_sec=0.0,
            )
            _write_manifest(run_dir, request.run_id, manifest_items)
            _write_status(run_dir, status)

        if appended_catalog_rows:
            append_catalog_rows(Path(request.output_root_path), appended_catalog_rows)

        _raise_if_delete_requested(run_dir, "finalize")
        status.current_item = None
        status.current_item_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0

        has_failures = status.items_failed > 0
        result.state = "failed" if has_failures else "completed"
        result.processed_count = status.items_done
        result.skipped_count = status.items_skipped
        result.error_count = status.items_failed
        result.batch_count = 0
        result.timeline_index_path = None
        result.warnings = warnings
        _write_run_performance_summary(
            run_dir=run_dir,
            request=request,
            status=status,
            manifest_items=manifest_items,
            run_wall_seconds=monotonic() - started,
        )
        _write_result(run_dir, result)

        status.state = "failed" if has_failures else "completed"
        status.current_stage = "failed" if has_failures else "completed"
        status.message = "Run finished with errors." if has_failures else "Run completed."
        status.warnings = warnings
        status.current_item = None
        status.current_item_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0
        status.progress_percent = 100.0
        status.completed_at = now_iso()
        _write_status(run_dir, status)
        append_log(
            log_path,
            f"[{now_iso()}] Run {'finished with errors' if has_failures else 'completed'} with {status.items_done} processed, {status.items_skipped} skipped, {status.items_failed} failed.",
        )
        return True
    except RunDeletionRequested as exc:
        delete_requested = True
        append_log(log_path, f"[{now_iso()}] Run canceled for deletion: {exc}")
        status.state = "canceled"
        status.current_stage = "canceled"
        status.message = "Deletion requested. Run canceled."
        status.warnings = warnings
        status.current_item = None
        status.current_item_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0
        status.progress_percent = max(status.progress_percent, 1.0)
        status.completed_at = now_iso()
        _write_status(run_dir, status)
        result.state = "canceled"
        result.processed_count = status.items_done
        result.skipped_count = status.items_skipped
        result.error_count = status.items_failed
        result.warnings = warnings
        _write_result(run_dir, result)
        return True
    except Exception as exc:
        append_log(log_path, f"[{now_iso()}] Run failed: {exc}")
        append_log(log_path, traceback.format_exc())
        status.state = "failed"
        status.current_stage = "failed"
        status.message = str(exc)
        status.warnings = warnings
        status.current_stage_elapsed_sec = 0.0
        status.progress_percent = max(status.progress_percent, 1.0)
        status.completed_at = now_iso()
        _write_status(run_dir, status)
        result.state = "failed"
        result.processed_count = status.items_done
        result.skipped_count = status.items_skipped
        result.error_count = status.items_failed + 1
        result.warnings = warnings + [tail_text(log_path, max_lines=30)]
        _write_run_performance_summary(
            run_dir=run_dir,
            request=request,
            status=status,
            manifest_items=manifest_items,
            run_wall_seconds=monotonic() - started,
        )
        _write_result(run_dir, result)
        return True
    finally:
        if lock_acquired:
            _release_run_lock(run_dir)
        if delete_requested:
            _delete_run_dir(run_dir, request)

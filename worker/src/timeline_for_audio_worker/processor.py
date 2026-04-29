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

from .acoustic_units import (
    ACOUSTIC_UNIT_BACKEND,
    ACOUSTIC_UNIT_MODEL_ID,
    ACOUSTIC_UNIT_TYPE,
    best_speaker_for_interval,
    generate_acoustic_unit_turns,
)
from .audio_features import build_speaker_count_metadata
from .artifacts import (
    register_artifact,
    render_ipa,
    render_readable_text,
    write_media_artifacts_index,
)
from .catalog import append_catalog_rows, catalog_key, catalog_path, load_catalog
from .context_builder import CONTEXT_BUILDER_VERSION, build_context_documents
from .contracts import JobRequest, JobResult, JobStatus, ManifestItem
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
from .reconstruction import ReconstructionResult
from .settings import configured_path, load_settings, uploads_root
from .vad_profile import vad_config_for_profile

_ITEM_STAGE_BOUNDS: dict[str, tuple[float, float]] = {
    "extract_audio": (0.0, 0.18),
    "detect_speech_candidates": (0.18, 0.30),
    "diarize_audio": (0.30, 0.70),
    "extract_acoustic_units": (0.70, 0.94),
    "generate_artifacts": (0.96, 1.0),
}

_JOB_LOCK_STALE_AFTER = timedelta(seconds=30)
_MIN_PREPROCESS_DURATION_SEC = 2.0
_PREFLIGHT_SKIPPED_STATUSES = {"skipped_invalid", "skipped_too_short"}
_DELETE_REQUEST_MARKER = ".delete-requested"


class JobDeletionRequested(RuntimeError):
    pass


def _job_log_path(job_dir: Path) -> Path:
    return job_dir / "logs" / "worker.log"


def _status_path(job_dir: Path) -> Path:
    return job_dir / "status.json"


def _result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def _manifest_path(job_dir: Path) -> Path:
    return job_dir / "manifest.json"


def _request_path(job_dir: Path) -> Path:
    return job_dir / "request.json"


def _lock_path(job_dir: Path) -> Path:
    return job_dir / ".job.lock"


def _delete_request_path(job_dir: Path) -> Path:
    return job_dir / _DELETE_REQUEST_MARKER


def _delete_requested(job_dir: Path) -> bool:
    return _delete_request_path(job_dir).exists()


def _raise_if_delete_requested(job_dir: Path, stage_name: str | None = None) -> None:
    if not _delete_requested(job_dir):
        return
    suffix = f" during {stage_name}" if stage_name else ""
    raise JobDeletionRequested(f"Deletion requested{suffix}.")


def _delete_upload_directories(request: JobRequest) -> None:
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


def _prune_catalog_rows(request: JobRequest | None, job_dir: Path) -> None:
    if request is None or not request.output_root_path:
        return
    path = catalog_path(Path(request.output_root_path))
    if not path.exists():
        return

    target_job_id = str(request.job_id or job_dir.name)
    target_run_dir = os.path.normcase(os.path.normpath(str(job_dir.resolve())))
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

        row_job_id = str(row.get("job_id") or "")
        row_run_dir = str(row.get("run_dir") or "")
        normalized_row_run_dir = ""
        if row_run_dir:
            try:
                normalized_row_run_dir = os.path.normcase(os.path.normpath(str(Path(row_run_dir).resolve())))
            except Exception:
                normalized_row_run_dir = os.path.normcase(os.path.normpath(row_run_dir))
        same_job = bool(target_job_id) and row_job_id.lower() == target_job_id.lower()
        same_run_dir = bool(normalized_row_run_dir) and normalized_row_run_dir == target_run_dir
        if same_job or same_run_dir:
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


def _delete_job_dir(job_dir: Path, request: JobRequest | None = None) -> None:
    if request is not None:
        _prune_catalog_rows(request, job_dir)
        _delete_upload_directories(request)
    shutil.rmtree(job_dir, ignore_errors=True)


def _resolve_duplicate_artifact_path(duplicate: dict[str, Any] | None) -> Path | None:
    if not duplicate:
        return None

    timeline_path = duplicate.get("timeline_path")
    if timeline_path:
        candidate = Path(str(timeline_path))
        if candidate.exists():
            return candidate

    run_dir = duplicate.get("run_dir")
    media_id = duplicate.get("audio_id") or duplicate.get("media_id")
    if run_dir and media_id:
        media_dir = Path(str(run_dir)) / "media" / str(media_id)
        for relative_path in (
            ("timeline", "speaker-acoustic-units-timeline.json"),
        ):
            candidate = media_dir.joinpath(*relative_path)
            if candidate.exists():
                return candidate

    return None


def _load_request(job_dir: Path) -> JobRequest:
    return JobRequest.from_dict(read_json(_request_path(job_dir)))


def _load_status(job_dir: Path) -> JobStatus:
    path = _status_path(job_dir)
    if not path.exists():
        return JobStatus(job_id=job_dir.name, updated_at=now_iso())
    return JobStatus(**read_json(path))


def _write_status(job_dir: Path, status: JobStatus) -> None:
    status.updated_at = now_iso()
    write_json_atomic(_status_path(job_dir), status.to_dict())


def _write_result(job_dir: Path, result: JobResult) -> None:
    write_json_atomic(_result_path(job_dir), result.to_dict())


def _write_manifest(job_dir: Path, job_id: str, items: list[ManifestItem]) -> None:
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "generated_at": now_iso(),
        "items": [item.to_dict() for item in items],
    }
    write_json_atomic(_manifest_path(job_dir), payload)


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


def _acquire_job_lock(job_dir: Path) -> bool:
    lock_path = _lock_path(job_dir)
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if not _job_lock_is_stale(job_dir):
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


def _release_job_lock(job_dir: Path) -> None:
    try:
        _lock_path(job_dir).unlink(missing_ok=True)
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


def _job_lock_is_stale(job_dir: Path) -> bool:
    lock_path = _lock_path(job_dir)
    if not lock_path.exists():
        return False
    status = _load_status(job_dir)
    if str(status.state or "").lower() != "running":
        return True
    updated_at = _parse_iso_timestamp(status.updated_at or status.started_at)
    if updated_at is None:
        return True
    return datetime.now(timezone.utc) - updated_at > _JOB_LOCK_STALE_AFTER


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


def _stage_expected_seconds(stage_name: str, media_duration_sec: float, compute_mode: str) -> float:
    safe_duration = max(1.0, media_duration_sec)
    if stage_name == "extract_audio":
        return max(1.5, min(25.0, safe_duration * 0.06))
    if stage_name == "transcribe_cleanup_source":
        factor = 0.18 if compute_mode == "gpu" else 0.90
        ceiling = 150.0 if compute_mode == "gpu" else 720.0
        return max(4.0, min(ceiling, safe_duration * factor))
    if stage_name == "prepare_cleanup_context":
        return max(1.0, min(12.0, safe_duration * 0.03))
    if stage_name == "transcribe_turns":
        factor = 0.22 if compute_mode == "gpu" else 1.10
        ceiling = 160.0 if compute_mode == "gpu" else 840.0
        return max(4.0, min(ceiling, safe_duration * factor))
    if stage_name == "diarize_audio":
        factor = 0.10 if compute_mode == "gpu" else 0.45
        ceiling = 120.0 if compute_mode == "gpu" else 480.0
        return max(2.0, min(ceiling, safe_duration * factor))
    if stage_name == "analyze_audio":
        return max(2.0, min(120.0, safe_duration * 0.12))
    if stage_name == "generate_artifacts":
        return max(1.0, min(15.0, safe_duration * 0.03))
    if stage_name == "llm_export":
        return 5.0
    if stage_name == "preflight":
        return max(1.0, min(10.0, safe_duration * 0.02))
    return 5.0


def _current_item_stage_fraction(
    stage_name: str, elapsed_sec: float, media_duration_sec: float, compute_mode: str
) -> float:
    lower, upper = _ITEM_STAGE_BOUNDS.get(stage_name, (0.0, 1.0))
    if upper <= lower:
        return upper
    expected = _stage_expected_seconds(stage_name, media_duration_sec, compute_mode)
    stage_progress = min(1.0, max(0.0, elapsed_sec / max(expected, 0.1)))
    return lower + ((upper - lower) * stage_progress)


def _overall_progress_percent(
    *,
    processed_duration_sec: float,
    total_duration_sec: float,
    current_stage: str,
    current_stage_elapsed_sec: float,
    current_media_duration_sec: float,
    compute_mode: str,
    preflight_fraction: float = 1.0,
    total_items: int = 0,
    completed_items: int = 0,
) -> float:
    if current_stage == "queued":
        return 0.0
    if current_stage == "preflight":
        return round(5.0 * min(1.0, max(0.0, preflight_fraction)), 1)
    if current_stage == "llm_export":
        export_fraction = min(
            1.0,
            max(
                0.0,
                current_stage_elapsed_sec
                / _stage_expected_seconds("llm_export", 1.0, compute_mode),
            ),
        )
        return round(95.0 + (4.0 * export_fraction), 1)
    if current_stage == "completed":
        return 100.0
    if total_duration_sec > 0:
        current_item_fraction = _current_item_stage_fraction(
            current_stage, current_stage_elapsed_sec, current_media_duration_sec, compute_mode
        )
        effective_processed = min(
            total_duration_sec,
            max(0.0, processed_duration_sec)
            + (max(0.0, current_media_duration_sec) * current_item_fraction),
        )
        duration_fraction = effective_processed / total_duration_sec
        return round(5.0 + (90.0 * duration_fraction), 1)

    if total_items <= 0:
        return 0.0

    current_item_fraction = _current_item_stage_fraction(
        current_stage, current_stage_elapsed_sec, current_media_duration_sec, compute_mode
    )
    completed_fraction = min(1.0, max(0.0, (completed_items + current_item_fraction) / total_items))
    return round(5.0 + (90.0 * completed_fraction), 1)


def _completed_progress_percent(
    *,
    processed_duration_sec: float,
    total_duration_sec: float,
    total_items: int,
    completed_items: int,
) -> float:
    if total_duration_sec > 0:
        completed_fraction = min(1.0, max(0.0, processed_duration_sec / total_duration_sec))
        return round(5.0 + (90.0 * completed_fraction), 1)

    if total_items <= 0:
        return 0.0

    completed_fraction = min(1.0, max(0.0, completed_items / total_items))
    return round(5.0 + (90.0 * completed_fraction), 1)


def _write_support_docs(job_dir: Path, request: JobRequest) -> None:
    vad_config = vad_config_for_profile(request.vad_profile)
    run_info = "\n".join(
        [
            "# Run Info",
            "",
            f"- Job ID: `{request.job_id}`",
            f"- Created At: `{request.created_at}`",
            f"- Profile: `{request.profile}`",
            f"- Compute Mode: `{request.compute_mode}`",
            f"- VAD Profile: `{request.vad_profile or ''}`",
            f"- Input Count: `{len(request.input_items)}`",
            f"- Reprocess Duplicates: `{request.reprocess_duplicates}`",
            "",
            "This run uses file-based coordination between CLI-created job files and the Python worker.",
            "",
        ]
    )
    conversion_info = "\n".join(
        [
            "# Conversion Info",
            "",
            f"- Acoustic unit backend: `{ACOUSTIC_UNIT_BACKEND}`",
            f"- Acoustic unit model: `{ACOUSTIC_UNIT_MODEL_ID}`",
            f"- Acoustic unit type: `{ACOUSTIC_UNIT_TYPE}`",
            f"- Compute mode: `{request.compute_mode}`",
            "- Diarization required: `True`",
            f"- Diarization model: `{request.diarization_model_id or ''}`",
            f"- VAD backend: `{request.vad_backend}` / `{request.vad_model_id}`",
            f"- VAD profile: `{request.vad_profile or ''}`",
            f"- VAD parameters: `{vad_config['vad_parameters']}`",
            f"- Pipeline version: `{request.pipeline_version}`",
            f"- Generation signature: `{request.generation_signature}`",
            "- Notes:",
            "  - TimelineForAudio does not interpret meaning or reconstruct readable text.",
            "  - The primary artifact is `timeline/speaker-acoustic-units-timeline.json`.",
            "  - Timestamps are mapped back to the original audio timeline.",
            "  - Speaker labels are mechanical labels such as `SPEAKER_00`; identities are not inferred.",
            "",
        ]
    )
    notice = "\n".join(
        [
            "# Notice",
            "",
            "- This run is optimized for local processing, not cloud transcription.",
            "- Model downloads may happen on first use and are cached afterward.",
            "- Speaker diarization is required. If pyannote prerequisites are missing, the item fails instead of producing fallback speaker labels.",
            "- Timeline timestamps are based on the original audio time.",
            "",
        ]
    )
    write_text(job_dir / "RUN_INFO.md", run_info)
    write_text(job_dir / "CONVERSION_INFO.md", conversion_info)
    write_text(job_dir / "NOTICE.md", notice)


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


def _timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def _write_timeline_readme(path: Path) -> None:
    lines = [
        "# Speaker Acoustic Units Timeline",
        "",
        "This directory contains the main TimelineForAudio artifact.",
        "",
        "- `speaker-acoustic-units-timeline.json`: speaker labels, original-audio timestamps, and acoustic units.",
        "- `source/source-record.json`: source file metadata used to preserve the original timeline.",
        "- `segments/speech-candidates.json`: speech candidate ranges used for efficient processing.",
        "- `ai-raw/speaker-turns.raw.json`: raw speaker diarization output normalized to JSON.",
        "- `ai-raw/acoustic-units.raw.json`: raw acoustic-unit extraction output normalized to JSON.",
        "",
        "TimelineForAudio does not infer real speaker names and does not reconstruct readable text.",
        "",
    ]
    write_text(path, "\n".join(lines))


def _write_timeline_preview(path: Path, payload: dict[str, Any]) -> None:
    source = payload.get("source") or {}
    lines = [
        "# Speaker Acoustic Units Timeline",
        "",
        f"- Source File: `{source.get('file_name') or source.get('display_name') or 'unknown'}`",
        f"- Recorded At: `{source.get('recorded_at') or 'unknown'}`",
        f"- Turn Count: `{payload.get('turn_count', 0)}`",
        "",
    ]
    for turn in payload.get("turns") or []:
        start = float(turn.get("start_sec", 0.0) or 0.0)
        end = float(turn.get("end_sec", start) or start)
        lines.extend(
            [
                f"## Turn {int(turn.get('index') or 0):03d}",
                f"Time: `{_timestamp_label(start)} - {_timestamp_label(end)}`",
                f"Speaker: `{turn.get('speaker') or 'SPEAKER_00'}`",
                f"Acoustic Units: `{turn.get('acoustic_units') or ''}`",
                "",
            ]
        )
    write_text(path, "\n".join(lines).rstrip() + "\n")


def _artifact_entry(
    *,
    media_dir: Path,
    kind: str,
    title: str,
    role: str,
    path: Path,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return {
        "kind": kind,
        "title": title,
        "display_name": title,
        "role": role,
        "format": path.suffix.lstrip(".").lower() or "text",
        "relative_path": path.relative_to(media_dir).as_posix(),
    }


def _process_one_item(
    *,
    job_dir: Path,
    request: JobRequest,
    item: Any,
    manifest_item: ManifestItem,
    on_stage: Callable[[str, str], None] | None = None,
    ensure_not_delete_requested: Callable[[str | None], None] | None = None,
) -> list[str]:
    source_path = _resolve_input_path(item)
    media_dir = ensure_dir(job_dir / "media" / str(manifest_item.media_id))
    source_dir = ensure_dir(media_dir / "source")
    segments_dir = ensure_dir(media_dir / "segments")
    raw_dir = ensure_dir(media_dir / "ai-raw")
    timeline_dir = ensure_dir(media_dir / "timeline")

    normalized_audio_path = source_dir / "audio-normalized.wav"
    speech_candidate_audio_path = segments_dir / "speech-candidates.wav"

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
    write_json_atomic(source_dir / "source-record.json", source_record)
    write_json_atomic(media_dir / "source.json", source_record)

    if on_stage:
        on_stage("detect_speech_candidates", "Detecting speech candidates.")
    vad_parameters = vad_config_for_profile(request.vad_profile)["vad_parameters"]
    cut_map = trim_audio(
        normalized_audio_path,
        speech_candidate_audio_path,
        manifest_item.duration_seconds,
        min_silence_duration_ms=int(vad_parameters.get("min_silence_duration_ms", 500)),
    )
    write_json_atomic(segments_dir / "speech-candidate-map.json", cut_map)
    write_json_atomic(segments_dir / "speech-candidates.json", _candidate_payload(cut_map))
    if ensure_not_delete_requested:
        ensure_not_delete_requested("detect_speech_candidates")

    if on_stage:
        on_stage("diarize_audio", "Running required speaker diarization.")
    speaker_payload = generate_speaker_turns(
        source_name=item.display_name,
        audio_path=normalized_audio_path,
        compute_mode=request.compute_mode,
    )
    write_json_atomic(raw_dir / "speaker-turns.raw.json", speaker_payload)
    if ensure_not_delete_requested:
        ensure_not_delete_requested("diarize_audio")

    speaker_metadata = build_speaker_count_metadata(
        {
            "diarization_used": True,
            "speaker_count": len(
                {
                    str(turn.get("speaker") or "").strip()
                    for turn in speaker_payload.get("turns", [])
                    if str(turn.get("speaker") or "").strip()
                }
            ),
            "speaker_turns": speaker_payload.get("turns", []),
        },
        {"diarization_used": True},
    )
    manifest_item.speaker_count = speaker_metadata["speaker_count"]
    manifest_item.speaker_count_status = speaker_metadata["speaker_count_status"]
    manifest_item.speaker_count_note = speaker_metadata["speaker_count_note"]

    if on_stage:
        on_stage("extract_acoustic_units", "Extracting acoustic units.")
    acoustic_result = generate_acoustic_unit_turns(
        audio_path=speech_candidate_audio_path,
        cut_map=cut_map,
        compute_mode=request.compute_mode,
    )
    acoustic_turn_rows = [
        {
            "index": turn.index,
            "start_sec": turn.start,
            "end_sec": turn.end,
            "acoustic_units": turn.acoustic_units,
            "unit_type": acoustic_result.unit_type,
            "confidence": turn.confidence,
        }
        for turn in acoustic_result.turns
    ]
    acoustic_payload = {
        "schema_version": 1,
        "backend": acoustic_result.backend_name,
        "model_id": acoustic_result.model_id,
        "status": acoustic_result.status,
        "unit_type": acoustic_result.unit_type,
        "warning_count": len(acoustic_result.warnings),
        "warnings": acoustic_result.warnings,
        "turn_count": len(acoustic_turn_rows),
        "turns": acoustic_turn_rows,
    }
    write_json_atomic(raw_dir / "acoustic-units.raw.json", acoustic_payload)
    if acoustic_result.status == "unavailable":
        raise RuntimeError(
            "; ".join(acoustic_result.warnings) or "Acoustic unit extraction failed."
        )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("extract_acoustic_units")

    if on_stage:
        on_stage("generate_artifacts", "Writing speaker acoustic unit timeline.")
    timeline_payload = _build_speaker_acoustic_units_timeline(
        source_record=source_record,
        speaker_payload=speaker_payload,
        acoustic_payload=acoustic_payload,
        conversion_signature=request.generation_signature,
        pipeline_version=request.pipeline_version,
    )
    timeline_json_path = timeline_dir / "speaker-acoustic-units-timeline.json"
    timeline_preview_path = timeline_dir / "speaker-acoustic-units-timeline.md"
    write_json_atomic(timeline_json_path, timeline_payload)
    _write_timeline_preview(timeline_preview_path, timeline_payload)
    _write_timeline_readme(media_dir / "README.md")

    artifacts = [
        entry
        for entry in [
            _artifact_entry(
                media_dir=media_dir,
                kind="speaker_acoustic_units_timeline",
                title="Speaker Acoustic Units Timeline",
                role="primary",
                path=timeline_json_path,
            ),
            _artifact_entry(
                media_dir=media_dir,
                kind="speaker_acoustic_units_timeline_preview",
                title="Speaker Acoustic Units Timeline Preview",
                role="support",
                path=timeline_preview_path,
            ),
            _artifact_entry(
                media_dir=media_dir,
                kind="raw_speaker_turns",
                title="Raw Speaker Turns",
                role="support",
                path=raw_dir / "speaker-turns.raw.json",
            ),
            _artifact_entry(
                media_dir=media_dir,
                kind="raw_acoustic_units",
                title="Raw Acoustic Units",
                role="support",
                path=raw_dir / "acoustic-units.raw.json",
            ),
            _artifact_entry(
                media_dir=media_dir,
                kind="speech_candidates",
                title="Speech Candidates",
                role="support",
                path=segments_dir / "speech-candidates.json",
            ),
            _artifact_entry(
                media_dir=media_dir,
                kind="source_record",
                title="Source Record",
                role="support",
                path=source_dir / "source-record.json",
            ),
        ]
        if entry is not None
    ]
    write_media_artifacts_index(
        media_dir=media_dir,
        media_id=str(manifest_item.media_id),
        primary_artifact_kind="speaker_acoustic_units_timeline",
        artifacts=artifacts,
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("generate_artifacts")
    return list(acoustic_result.warnings)


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


def _candidate_payload(cut_map: list[dict[str, float]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "candidate_count": len(cut_map),
        "candidates": [
            {
                "index": index,
                "start_sec": float(row.get("original_start", 0.0) or 0.0),
                "end_sec": float(row.get("original_end", 0.0) or 0.0),
                "trimmed_start_sec": float(row.get("trimmed_start", 0.0) or 0.0),
                "trimmed_end_sec": float(row.get("trimmed_end", 0.0) or 0.0),
            }
            for index, row in enumerate(cut_map, start=1)
        ],
    }


def _build_speaker_acoustic_units_timeline(
    *,
    source_record: dict[str, Any],
    speaker_payload: dict[str, Any],
    acoustic_payload: dict[str, Any],
    conversion_signature: str,
    pipeline_version: str,
) -> dict[str, Any]:
    recorded_at = source_record.get("recorded_at")
    speaker_turns = list(speaker_payload.get("turns") or [])
    raw_turns = list(acoustic_payload.get("turns") or [])
    turns: list[dict[str, Any]] = []
    for index, turn in enumerate(raw_turns, start=1):
        start = float(turn.get("start_sec", turn.get("start", 0.0)) or 0.0)
        end = float(turn.get("end_sec", turn.get("end", start)) or start)
        speaker = best_speaker_for_interval(start, end, speaker_turns)
        turns.append(
            {
                "index": index,
                "start_sec": start,
                "end_sec": end,
                "absolute_start_at": _absolute_at(recorded_at, start),
                "absolute_end_at": _absolute_at(recorded_at, end),
                "speaker": speaker,
                "acoustic_units": str(turn.get("acoustic_units") or ""),
                "unit_type": str(acoustic_payload.get("unit_type") or ACOUSTIC_UNIT_TYPE),
                "confidence": turn.get("confidence"),
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "speaker-acoustic-units-timeline",
        "source": source_record,
        "pipeline": {
            "pipeline_version": pipeline_version,
            "generation_signature": conversion_signature,
            "speaker_backend": speaker_payload.get("backend"),
            "speaker_model_id": speaker_payload.get("model_id"),
            "acoustic_unit_backend": acoustic_payload.get("backend"),
            "acoustic_unit_model_id": acoustic_payload.get("model_id"),
            "unit_type": acoustic_payload.get("unit_type"),
        },
        "turn_count": len(turns),
        "turns": turns,
    }


def _job_sources_accessible(job_dir: Path) -> bool:
    try:
        request = _load_request(job_dir)
    except Exception:
        return False
    return all(_resolve_input_path(item).exists() for item in request.input_items)


def _make_media_id(item: Any, file_hash: str) -> str:
    stem = slugify(Path(item.display_name or Path(item.original_path).stem).stem)
    identity = str(getattr(item, "source_file_identity", "") or "").strip()
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8] if identity else file_hash[:8]
    return f"{stem}-{suffix or short_id()}"


def _collect_pending_jobs() -> list[Path]:
    return _collect_jobs_by_state("pending")


def _collect_running_jobs() -> list[Path]:
    return _collect_jobs_by_state("running")


def _claim_recoverable_running_job() -> tuple[Path | None, bool]:
    running_jobs = _collect_running_jobs()
    for candidate in running_jobs:
        if not _job_lock_is_stale(candidate):
            continue
        if not _job_sources_accessible(candidate):
            continue
        if not _acquire_job_lock(candidate):
            continue
        return candidate, True
    return None, bool(running_jobs)


def _collect_jobs_by_state(*states: str) -> list[Path]:
    target_states = {state.lower() for state in states}
    settings = load_settings()
    rows: list[Path] = []
    for root in settings.get("outputRoots", []):
        if not root.get("enabled", True):
            continue
        root_path = Path(str(root.get("path") or ""))
        if not root_path.exists():
            continue
        job_dirs = list(root_path.glob("job-*"))
        job_dirs.extend(root_path.glob("run-*"))
        for candidate in sorted({item.resolve(): item for item in job_dirs}.values()):
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
def _process_one_item_legacy(
    *,
    job_dir: Path,
    request: JobRequest,
    item: Any,
    manifest_item: ManifestItem,
    on_stage: Callable[[str, str], None] | None = None,
    ensure_not_delete_requested: Callable[[str | None], None] | None = None,
) -> list[str]:
    source_path = _resolve_input_path(item)
    media_dir = ensure_dir(job_dir / "media" / str(manifest_item.media_id))
    audio_dir = ensure_dir(media_dir / "audio")
    ai_raw_dir = ensure_dir(media_dir / "ai-raw")
    transcript_dir = ensure_dir(media_dir / "transcript")
    analysis_dir = ensure_dir(media_dir / "analysis")
    debug_ipa_dir = ensure_dir(media_dir / "debug" / "text-derived-ipa")
    ipa_dir = ensure_dir(media_dir / "ipa")
    readable_text_dir = media_dir / "readable-text"

    source_info = {
        "job_id": request.job_id,
        "audio_id": manifest_item.media_id,
        "input_id": item.input_id,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "source_relative_path": getattr(item, "source_relative_path", None),
        "source_file_identity": getattr(item, "source_file_identity", None),
        "original_path": item.original_path,
        "resolved_path": str(source_path),
        "display_name": item.display_name,
        "size_bytes": manifest_item.size_bytes,
        "duration_seconds": manifest_item.duration_seconds,
        "source_hash": manifest_item.sha256,
        "conversion_signature": manifest_item.conversion_signature,
        "generation_signature": manifest_item.generation_signature,
        "recorded_at": manifest_item.captured_at,
        "captured_at": manifest_item.captured_at,
        "container_name": manifest_item.container_name,
        "extension": manifest_item.extension,
        "audio_codec": manifest_item.audio_codec,
        "audio_channels": manifest_item.audio_channels,
        "audio_sample_rate": manifest_item.audio_sample_rate,
        "bitrate": manifest_item.bitrate,
        "model_id": manifest_item.model_id,
        "pipeline_version": manifest_item.pipeline_version,
        "language_hint": request.language_hint,
        "supplemental_context_configured": bool(request.supplemental_context_text),
        "ipa_cleanup_rules_version": request.context_builder_version or CONTEXT_BUILDER_VERSION,
        "requested_ipa_backend": request.ipa_backend,
        "readable_text_enabled": request.readable_text_enabled,
        "reconstruction_backend": request.reconstruction_backend,
        "reconstruction_model_id": request.reconstruction_model_id,
        "reconstruction_prompt_version": request.reconstruction_prompt_version,
        "diarization_enabled": True,
        "diarization_required": True,
        "diarization_model_id": request.diarization_model_id,
        "vad_backend": request.vad_backend,
        "vad_model_id": request.vad_model_id,
        "vad_profile": request.vad_profile,
        "vad_parameters": vad_config_for_profile(request.vad_profile)["vad_parameters"],
    }
    write_json_atomic(media_dir / "source.json", source_info)

    source_normalized_audio_path = audio_dir / "source-normalized.wav"
    normalized_audio_path = audio_dir / "normalized.wav"

    if ensure_not_delete_requested:
        ensure_not_delete_requested("extract_audio")
    if on_stage:
        on_stage("extract_audio", "Preparing audio input.")
    extract_audio(source_path, source_normalized_audio_path)
    cut_map = trim_audio(
        source_normalized_audio_path,
        normalized_audio_path,
        manifest_item.duration_seconds,
        min_silence_duration_ms=int(
            vad_config_for_profile(request.vad_profile)["vad_parameters"].get(
                "min_silence_duration_ms",
                500,
            )
        ),
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("extract_audio")
    write_json_atomic(audio_dir / "cut_map.json", cut_map)
    timeline_payload = write_timeline_events(
        source_info=source_info,
        source_name=item.display_name,
        duration_seconds=manifest_item.duration_seconds,
        cut_map=cut_map,
        output_dir=analysis_dir,
    )
    source_info["full_timeline_audio_path"] = str(source_normalized_audio_path)
    source_info["speech_candidate_audio_path"] = str(normalized_audio_path)
    source_info["cut_map_path"] = "audio/cut_map.json"
    source_info["timeline_events_path"] = "analysis/timeline_events.json"
    source_info["speech_candidate_count"] = timeline_payload.get("speech_candidate_count", 0)
    source_info["silence_or_noise_candidate_count"] = timeline_payload.get(
        "silence_or_noise_candidate_count", 0
    )
    write_json_atomic(media_dir / "source.json", source_info)

    if ensure_not_delete_requested:
        ensure_not_delete_requested("transcribe_cleanup_source")
    if on_stage:
        on_stage("transcribe_cleanup_source", "Preparing IPA cleanup source.")
    cleanup_source_payload = transcribe_audio(
        source_name=item.display_name,
        audio_path=normalized_audio_path,
        transcript_dir=transcript_dir,
        artifact_stem="cleanup-source",
        transcript_label="cleanup_source",
        cut_map=cut_map,
        compute_mode=request.compute_mode,
        initial_prompt=None,
        diarization_enabled=False,
        word_timestamps=False,
        vad_profile=request.vad_profile,
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("transcribe_cleanup_source")

    if on_stage:
        on_stage("prepare_cleanup_context", "Preparing supplemental cleanup context.")
    context_report = build_context_documents(
        transcript_dir=transcript_dir,
        transcript_payload=cleanup_source_payload,
        supplemental_context_text=request.supplemental_context_text,
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("prepare_cleanup_context")
    merged_context_path = transcript_dir / "context_merged.txt"
    merged_context = (
        merged_context_path.read_text(encoding="utf-8", errors="replace")
        if merged_context_path.exists()
        else ""
    )

    if on_stage:
        on_stage("transcribe_turns", "Generating turn-aligned text.")
    voice_to_text_payload = transcribe_audio(
        source_name=item.display_name,
        audio_path=normalized_audio_path,
        transcript_dir=ai_raw_dir,
        artifact_stem="voice-to-text",
        transcript_label="voice_to_text",
        cut_map=cut_map,
        compute_mode=request.compute_mode,
        initial_prompt=merged_context,
        diarization_enabled=True,
        word_timestamps=True,
        vad_profile=request.vad_profile,
    )
    write_json_atomic(ai_raw_dir / "voice-to-text.json", voice_to_text_payload)
    if ensure_not_delete_requested:
        ensure_not_delete_requested("transcribe_turns")

    if on_stage:
        on_stage("diarize_audio", "Aligning speaker turns.")
    turns_source_payload = apply_speaker_diarization(
        source_name=item.display_name,
        audio_path=source_normalized_audio_path,
        transcript_dir=transcript_dir,
        analysis_dir=analysis_dir,
        raw_ai_dir=ai_raw_dir,
        transcript_payload=voice_to_text_payload,
        compute_mode=request.compute_mode,
        artifact_stem="voice-to-text-with-speakers",
    )
    write_json_atomic(transcript_dir / "voice-to-text-with-speakers.json", turns_source_payload)
    write_json_atomic(
        analysis_dir / "speaker-assignment.json",
        {
            "source_name": item.display_name,
            "diarization_used": turns_source_payload.get("diarization_used", False),
            "diarization_error": turns_source_payload.get("diarization_error"),
            "speaker_assignment_method": turns_source_payload.get("speaker_assignment_method"),
            "speaker_turns": turns_source_payload.get("speaker_turns", []),
            "speaker_segments": turns_source_payload.get("speaker_segments", []),
            "words": turns_source_payload.get("words", []),
        },
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("diarize_audio")

    write_transcript_delta(
        transcript_dir=transcript_dir,
        cleanup_source_payload=cleanup_source_payload,
        turns_source_payload=turns_source_payload,
    )
    if on_stage:
        on_stage("analyze_audio", "Collecting timing and audio summaries.")
    speaker_summary = write_speaker_summary(
        source_name=item.display_name,
        output_dir=analysis_dir,
        transcript_payload=turns_source_payload,
    )
    speaker_count_metadata = build_speaker_count_metadata(speaker_summary, turns_source_payload)
    manifest_item.speaker_count = speaker_count_metadata["speaker_count"]
    manifest_item.speaker_count_status = speaker_count_metadata["speaker_count_status"]
    manifest_item.speaker_count_note = speaker_count_metadata["speaker_count_note"]
    audio_feature_summary = analyze_audio(
        source_name=item.display_name,
        audio_path=source_normalized_audio_path,
        duration_seconds=manifest_item.duration_seconds,
        transcript_payload=turns_source_payload,
        output_dir=analysis_dir,
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("analyze_audio")
    manifest_item.pause_summary = audio_feature_summary.get("pause_summary", {})
    manifest_item.loudness_summary = audio_feature_summary.get("loudness_summary", {})
    manifest_item.speaking_rate_summary = audio_feature_summary.get("speaking_rate_summary", {})
    manifest_item.pitch_summary = audio_feature_summary.get("pitch_summary", {})
    manifest_item.speaker_confidence_summary = audio_feature_summary.get(
        "speaker_confidence_summary", {}
    )
    manifest_item.diarization_quality_summary = audio_feature_summary.get(
        "diarization_quality_summary", {}
    )
    manifest_item.optional_voice_feature_summary = audio_feature_summary.get(
        "optional_voice_feature_summary", {}
    )
    if on_stage:
        on_stage(
            "generate_artifacts",
            "Writing IPA and readable text artifacts."
            if request.readable_text_enabled
            else "Writing IPA artifacts.",
        )
    audio_ipa_result = generate_audio_ipa_turns(
        audio_path=normalized_audio_path,
        cut_map=cut_map,
        preferred_backend=request.ipa_backend,
        compute_mode=request.compute_mode,
    )
    audio_ipa_turn_rows = [
        {
            "index": turn.index,
            "start": turn.start,
            "end": turn.end,
            "speaker": turn.speaker,
            "ipa": turn.ipa,
            "confidence": getattr(turn, "confidence", None),
        }
        for turn in audio_ipa_result.turns
    ]
    render_ipa(
        output_path=ai_raw_dir / "Voice to IPA.md",
        source_info=source_info,
        backend_name=audio_ipa_result.backend_name,
        status=audio_ipa_result.status,
        warnings=audio_ipa_result.warnings,
        speaker_count=None,
        speaker_count_status=None,
        speaker_count_note=None,
        turns=audio_ipa_turn_rows,
    )
    write_json_atomic(
        ai_raw_dir / "voice-to-ipa.json",
        {
            "requested_backend": request.ipa_backend,
            "backend": audio_ipa_result.backend_name,
            "status": audio_ipa_result.status,
            "source_type": audio_ipa_result.source_type,
            "warning_count": len(audio_ipa_result.warnings),
            "warnings": audio_ipa_result.warnings,
            "turn_count": len(audio_ipa_result.turns),
            "turns": audio_ipa_turn_rows,
        },
    )
    source_info["voice_to_ipa_markdown_path"] = "ai-raw/Voice to IPA.md"
    source_info["voice_to_ipa_path"] = "ai-raw/voice-to-ipa.json"
    source_info["voice_to_text_path"] = "ai-raw/voice-to-text.json"
    source_info["voice_to_text_with_speakers_path"] = "transcript/voice-to-text-with-speakers.json"
    source_info["speaker_diarization_path"] = "ai-raw/speaker-diarization.json"
    source_info["speaker_assignment_path"] = "analysis/speaker-assignment.json"

    ipa_result = align_ipa_turns_to_speakers(
        ipa_result=audio_ipa_result,
        speaker_payload=turns_source_payload,
    )
    text_derived_ipa_result = generate_ipa_turns(
        transcript_payload=turns_source_payload,
        preferred_backend=request.ipa_backend,
    )
    if (
        request.ipa_backend == EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND
        and text_derived_ipa_result.backend_name
        not in {EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND, "segment-ipa-passthrough"}
    ):
        raise RuntimeError(
            "Requested pyopenjtalk IPA backend did not run. Install pyopenjtalk or use --ipa-backend sudachi."
        )
    source_info["effective_ipa_backend"] = ipa_result.backend_name
    source_info["effective_ipa_source_type"] = ipa_result.source_type
    source_info["text_derived_ipa_backend"] = text_derived_ipa_result.backend_name
    source_info["text_derived_ipa_source_type"] = text_derived_ipa_result.source_type
    source_info["text_derived_ipa_markdown_path"] = "debug/text-derived-ipa/Text Derived IPA.md"
    source_info["text_derived_ipa_turns_path"] = "debug/text-derived-ipa/text_derived_ipa_turns.json"
    write_json_atomic(media_dir / "source.json", source_info)
    ipa_path = ipa_dir / "IPA.md"
    ipa_turn_rows = [
        {
            "index": turn.index,
            "start": turn.start,
            "end": turn.end,
            "speaker": turn.speaker,
            "ipa": turn.ipa,
            "confidence": getattr(turn, "confidence", None),
        }
        for turn in ipa_result.turns
    ]
    text_derived_ipa_turn_rows = [
        {
            "index": turn.index,
            "start": turn.start,
            "end": turn.end,
            "speaker": turn.speaker,
            "ipa": turn.ipa,
            "confidence": getattr(turn, "confidence", None),
        }
        for turn in text_derived_ipa_result.turns
    ]
    render_ipa(
        output_path=ipa_path,
        source_info=source_info,
        backend_name=ipa_result.backend_name,
        status=ipa_result.status,
        warnings=ipa_result.warnings,
        speaker_count=manifest_item.speaker_count,
        speaker_count_status=manifest_item.speaker_count_status,
        speaker_count_note=manifest_item.speaker_count_note,
        turns=ipa_turn_rows,
    )
    write_json_atomic(
        ipa_dir / "ipa_turns.json",
        {
            "requested_backend": request.ipa_backend,
            "backend": ipa_result.backend_name,
            "status": ipa_result.status,
            "source_type": ipa_result.source_type,
            "warning_count": len(ipa_result.warnings),
            "warnings": ipa_result.warnings,
            "turn_count": len(ipa_result.turns),
            "turns": ipa_turn_rows,
        },
    )
    render_ipa(
        output_path=debug_ipa_dir / "Text Derived IPA.md",
        source_info=source_info,
        backend_name=text_derived_ipa_result.backend_name,
        status=text_derived_ipa_result.status,
        warnings=text_derived_ipa_result.warnings,
        speaker_count=manifest_item.speaker_count,
        speaker_count_status=manifest_item.speaker_count_status,
        speaker_count_note=manifest_item.speaker_count_note,
        turns=text_derived_ipa_turn_rows,
    )
    write_json_atomic(
        debug_ipa_dir / "text_derived_ipa_turns.json",
        {
            "requested_backend": request.ipa_backend,
            "backend": text_derived_ipa_result.backend_name,
            "status": text_derived_ipa_result.status,
            "source_type": text_derived_ipa_result.source_type,
            "warning_count": len(text_derived_ipa_result.warnings),
            "warnings": text_derived_ipa_result.warnings,
            "turn_count": len(text_derived_ipa_result.turns),
            "turns": text_derived_ipa_turn_rows,
        },
    )
    write_review_artifact(
        media_dir=media_dir,
        source_info=source_info,
        transcript_payload=turns_source_payload,
        ipa_turns=ipa_turn_rows,
        preferred_backend=request.ipa_backend,
        speaker_count=manifest_item.speaker_count,
    )
    readable_text_turn_count = 0
    readable_text_warnings: list[str] = []
    readable_text_status = "disabled"
    readable_text_path = readable_text_dir / "Readable Text.md"
    if request.readable_text_enabled:
        readable_text_dir = ensure_dir(readable_text_dir)
        if ipa_result.turns:
            readable_text_result = reconstruct_readable_text(
                transcript_payload=turns_source_payload,
                ipa_result=ipa_result,
                language_hint=request.language_hint,
                supplemental_context_text=request.supplemental_context_text,
                compute_mode=request.compute_mode,
            )
        else:
            readable_text_result = ReconstructionResult(
                backend_name="audio-ipa-required-readable-text-unavailable-v1",
                status="unavailable",
                turns=[],
                warnings=[
                    "Readable Text was not generated because the primary audio-to-IPA stage did not produce IPA turns."
                ],
                model_id=request.reconstruction_model_id,
                prompt_version=request.reconstruction_prompt_version,
                requested_compute_mode=request.compute_mode,
                effective_device=None,
                decoding=None,
            )
        readable_text_status = readable_text_result.status
        readable_text_warnings = list(readable_text_result.warnings)
        readable_text_turn_count = len(readable_text_result.turns)
        readable_text_turn_rows = [
            {
                "index": turn.index,
                "start": turn.start,
                "end": turn.end,
                "speaker": turn.speaker,
                "text": turn.text,
            }
            for turn in readable_text_result.turns
        ]
        write_json_atomic(
            readable_text_dir / "reconstruction.json",
            {
                "backend": readable_text_result.backend_name,
                "status": readable_text_result.status,
                "model_id": readable_text_result.model_id,
                "prompt_version": readable_text_result.prompt_version,
                "requested_compute_mode": readable_text_result.requested_compute_mode,
                "effective_device": readable_text_result.effective_device,
                "decoding": readable_text_result.decoding,
                "warning_count": len(readable_text_result.warnings),
                "warnings": readable_text_result.warnings,
                "turn_count": len(readable_text_result.turns),
            },
        )
        write_json_atomic(
            readable_text_dir / "readable_text_turns.json",
            {
                "backend": readable_text_result.backend_name,
                "status": readable_text_result.status,
                "model_id": readable_text_result.model_id,
                "prompt_version": readable_text_result.prompt_version,
                "requested_compute_mode": readable_text_result.requested_compute_mode,
                "effective_device": readable_text_result.effective_device,
                "decoding": readable_text_result.decoding,
                "warning_count": len(readable_text_result.warnings),
                "warnings": readable_text_result.warnings,
                "turn_count": len(readable_text_result.turns),
                "turns": readable_text_turn_rows,
            },
        )
        render_readable_text(
            output_path=readable_text_path,
            source_info=source_info,
            turns=readable_text_turn_rows,
            warnings=readable_text_result.warnings,
            speaker_count=manifest_item.speaker_count,
            speaker_count_status=manifest_item.speaker_count_status,
            speaker_count_note=manifest_item.speaker_count_note,
        )
    artifacts: list[dict[str, Any]] = []
    ipa_artifact = register_artifact(
        media_dir=media_dir,
        kind="ipa",
        title="IPA",
        display_name="IPA",
        role="secondary"
        if request.readable_text_enabled and readable_text_turn_count > 0 and ipa_result.turns
        else "primary"
        if ipa_result.turns
        else "pending",
        path=ipa_path,
    )
    if ipa_artifact is not None:
        artifacts.append(ipa_artifact)
    voice_to_ipa_artifact = register_artifact(
        media_dir=media_dir,
        kind="voice_to_ipa",
        title="Voice to IPA",
        display_name="Voice to IPA",
        role="support",
        path=ai_raw_dir / "Voice to IPA.md",
    )
    if voice_to_ipa_artifact is not None:
        artifacts.append(voice_to_ipa_artifact)
    voice_to_text_artifact = register_artifact(
        media_dir=media_dir,
        kind="voice_to_text",
        title="Voice to Text",
        display_name="Voice to Text",
        role="support",
        path=ai_raw_dir / "voice-to-text.json",
    )
    if voice_to_text_artifact is not None:
        artifacts.append(voice_to_text_artifact)
    voice_to_text_with_speakers_artifact = register_artifact(
        media_dir=media_dir,
        kind="voice_to_text_with_speakers",
        title="Voice to Text with Speakers",
        display_name="Voice to Text with Speakers",
        role="support",
        path=transcript_dir / "voice-to-text-with-speakers.json",
    )
    if voice_to_text_with_speakers_artifact is not None:
        artifacts.append(voice_to_text_with_speakers_artifact)
    speaker_diarization_artifact = register_artifact(
        media_dir=media_dir,
        kind="speaker_diarization",
        title="Speaker Diarization",
        display_name="Speaker Diarization",
        role="support",
        path=ai_raw_dir / "speaker-diarization.json",
    )
    if speaker_diarization_artifact is not None:
        artifacts.append(speaker_diarization_artifact)
    speaker_assignment_artifact = register_artifact(
        media_dir=media_dir,
        kind="speaker_assignment",
        title="Speaker Assignment",
        display_name="Speaker Assignment",
        role="support",
        path=analysis_dir / "speaker-assignment.json",
    )
    if speaker_assignment_artifact is not None:
        artifacts.append(speaker_assignment_artifact)
    timeline_events_artifact = register_artifact(
        media_dir=media_dir,
        kind="timeline_events",
        title="Timeline Events",
        display_name="Timeline Events",
        role="support",
        path=analysis_dir / "Timeline Events.md",
    )
    if timeline_events_artifact is not None:
        artifacts.append(timeline_events_artifact)
    review_artifact = register_artifact(
        media_dir=media_dir,
        kind="review",
        title="IPA Review",
        display_name="IPA Review",
        role="support",
        path=media_dir / "review" / "review.html",
    )
    if review_artifact is not None:
        artifacts.append(review_artifact)
    if request.readable_text_enabled:
        readable_text_artifact = register_artifact(
            media_dir=media_dir,
            kind="readable_text",
            title="Readable Text",
            display_name="可読テキスト",
            role="primary" if readable_text_turn_count > 0 else "pending",
            path=readable_text_path,
        )
        if readable_text_artifact is not None:
            artifacts.append(readable_text_artifact)
    write_process_review_artifact(
        media_dir=media_dir,
        source_info=source_info,
        cleanup_source_payload=cleanup_source_payload,
        turns_source_payload=turns_source_payload,
        timeline_payload=timeline_payload,
        ipa_turns=ipa_turn_rows,
        readable_text_enabled=request.readable_text_enabled,
        readable_text_turn_count=readable_text_turn_count,
    )
    process_review_artifact = register_artifact(
        media_dir=media_dir,
        kind="process_review",
        title="Processing Review",
        display_name="Processing Review",
        role="support",
        path=media_dir / "review" / "process.html",
    )
    if process_review_artifact is not None:
        artifacts.append(process_review_artifact)
    write_media_artifacts_index(
        media_dir=media_dir,
        media_id=str(manifest_item.media_id),
        primary_artifact_kind="readable_text"
        if request.readable_text_enabled and readable_text_turn_count > 0
        else "ipa",
        artifacts=artifacts,
    )
    if ensure_not_delete_requested:
        ensure_not_delete_requested("generate_artifacts")
    warnings: list[str] = []
    for payload in (cleanup_source_payload, turns_source_payload):
        prefix = str(payload.get("transcript_label") or payload.get("artifact_stem") or "transcript")
        for warning in payload.get("transcription_warnings", []) or []:
            if str(warning).strip():
                warnings.append(f"{prefix}: {warning}")
        if payload.get("diarization_requested") and payload.get("diarization_error"):
            warnings.append(f"{prefix} diarization: {payload['diarization_error']}")
    if context_report.get("merged_context_truncated"):
        warnings.append("prepare_cleanup_context: merged context was truncated before turn alignment.")
    if ipa_result.status != "unavailable":
        warnings.extend(ipa_result.warnings)
    if request.readable_text_enabled and readable_text_status != "unavailable":
        warnings.extend(readable_text_warnings)
    return warnings


def process_job(job_dir: Path | None = None) -> bool:
    lock_acquired = False
    delete_requested = False
    if job_dir is None:
        running_job_dir, has_running_jobs = _claim_recoverable_running_job()
        if running_job_dir is not None:
            job_dir = running_job_dir
            lock_acquired = True
        else:
            if has_running_jobs:
                return False
            pending = _collect_pending_jobs()
            if not pending:
                return False
            job_dir = None
            for candidate in pending:
                if not _job_sources_accessible(candidate):
                    continue
                if not _acquire_job_lock(candidate):
                    continue
                job_dir = candidate
                lock_acquired = True
                break
            if job_dir is None:
                return False

    job_dir = job_dir.resolve()
    if not _request_path(job_dir).exists():
        return False
    if not lock_acquired and not _acquire_job_lock(job_dir):
        return False
    lock_acquired = True

    log_path = _job_log_path(job_dir)
    request = _load_request(job_dir)
    _raise_if_delete_requested(job_dir, "queued")
    _write_support_docs(job_dir, request)
    status = JobStatus(
        job_id=request.job_id,
        state="running",
        current_stage="preflight",
        message="Preparing job.",
        items_total=len(request.input_items),
        progress_percent=1.0 if request.input_items else 0.0,
        started_at=now_iso(),
    )
    result = JobResult(
        job_id=request.job_id,
        state="running",
        run_dir=str(job_dir),
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
        _raise_if_delete_requested(job_dir, stage_name)

    try:
        _write_status(job_dir, status)
        _write_result(job_dir, result)
        append_log(log_path, f"[{now_iso()}] Starting job {request.job_id}")
        for index, input_item in enumerate(request.input_items, start=1):
            _raise_if_delete_requested(job_dir, "preflight")
            status.current_media = input_item.display_name
            status.message = (
                f"Preflight {index}/{len(request.input_items)}: {input_item.display_name}"
            )
            status.progress_percent = _overall_progress_percent(
                processed_duration_sec=0.0,
                total_duration_sec=0.0,
                current_stage="preflight",
                current_stage_elapsed_sec=0.0,
                current_media_duration_sec=0.0,
                compute_mode=compute_mode,
                preflight_fraction=index / max(len(request.input_items), 1),
                total_items=max(len(request.input_items), 1),
            )
            _write_status(job_dir, status)
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
                status.videos_skipped += 1
                _write_manifest(job_dir, request.job_id, manifest_items)
                _write_status(job_dir, status)
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
                status.videos_skipped += 1
                _write_manifest(job_dir, request.job_id, manifest_items)
                _write_status(job_dir, status)
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
        status.videos_total = len(manifest_items)
        status.total_duration_sec = round(total_duration, 3)
        status.current_media = None
        status.message = "Preflight completed."
        status.progress_percent = 5.0 if manifest_items else 0.0
        _write_manifest(job_dir, request.job_id, manifest_items)
        _write_status(job_dir, status)
        append_log(log_path, f"[{now_iso()}] Preflight complete for {len(manifest_items)} item(s).")
        eta_predictor = build_eta_predictor(
            output_root=Path(request.output_root_path),
            current_job_id=request.job_id,
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
            _raise_if_delete_requested(job_dir, "extract_audio")
            if manifest_item.status in _PREFLIGHT_SKIPPED_STATUSES:
                append_log(
                    log_path,
                    f"[{now_iso()}] Skipped after preflight classification "
                    f"({manifest_item.status}): {input_item.original_path}",
                )
                continue
            status.current_media = input_item.display_name
            status.current_media_elapsed_sec = 0.0
            status.current_stage_elapsed_sec = 0.0
            status.current_stage = "extract_audio"
            status.message = f"Processing {index}/{len(manifest_items)}: {input_item.display_name}"
            status.progress_percent = _overall_progress_percent(
                processed_duration_sec=status.processed_duration_sec,
                total_duration_sec=status.total_duration_sec,
                current_stage="extract_audio",
                current_stage_elapsed_sec=0.0,
                current_media_duration_sec=manifest_item.duration_seconds,
                compute_mode=compute_mode,
                total_items=max(len(manifest_items), 1),
                completed_items=status.videos_done + status.videos_skipped + status.videos_failed,
            )
            _write_status(job_dir, status)

            if manifest_item.duplicate_status == "duplicate_skip":
                manifest_item.status = "skipped_duplicate"
                manifest_item.processing_wall_seconds = 0.0
                manifest_item.stage_elapsed_seconds = {}
                status.videos_skipped += 1
                status.processed_duration_sec = round(
                    status.processed_duration_sec + manifest_item.duration_seconds, 3
                )
                status.current_stage_elapsed_sec = 0.0
                status.progress_percent = _completed_progress_percent(
                    processed_duration_sec=status.processed_duration_sec,
                    total_duration_sec=status.total_duration_sec,
                    total_items=max(len(manifest_items), 1),
                    completed_items=status.videos_done
                    + status.videos_skipped
                    + status.videos_failed,
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
                _write_manifest(job_dir, request.job_id, manifest_items)
                _write_status(job_dir, status)
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
                    completed_count = (
                        status.videos_done + status.videos_skipped + status.videos_failed
                    )
                    current_fraction = _current_item_stage_fraction(
                        stage_name,
                        current_stage_elapsed,
                        manifest_item.duration_seconds,
                        compute_mode,
                    )
                    effective_processed = status.processed_duration_sec + (
                        manifest_item.duration_seconds * current_fraction
                    )
                    status.current_media_elapsed_sec = round(elapsed, 3)
                    status.current_stage_elapsed_sec = current_stage_elapsed
                    status.progress_percent = max(
                        status.progress_percent,
                        _overall_progress_percent(
                            processed_duration_sec=status.processed_duration_sec,
                            total_duration_sec=status.total_duration_sec,
                            current_stage=stage_name,
                            current_stage_elapsed_sec=current_stage_elapsed,
                            current_media_duration_sec=manifest_item.duration_seconds,
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
                    _write_status(job_dir, status)

            heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
            heartbeat_thread.start()

            def stage_update(stage_name: str, message: str) -> None:
                _raise_if_delete_requested(job_dir, stage_name)
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
                status.current_media = input_item.display_name
                status.current_media_elapsed_sec = round(elapsed, 3)
                status.current_stage_elapsed_sec = current_stage_elapsed
                status.progress_percent = max(
                    status.progress_percent,
                    _overall_progress_percent(
                        processed_duration_sec=status.processed_duration_sec,
                        total_duration_sec=status.total_duration_sec,
                        current_stage=stage_name,
                        current_stage_elapsed_sec=current_stage_elapsed,
                        current_media_duration_sec=manifest_item.duration_seconds,
                        compute_mode=compute_mode,
                        total_items=max(len(manifest_items), 1),
                        completed_items=status.videos_done
                        + status.videos_skipped
                        + status.videos_failed,
                    ),
                )
                current_fraction = _current_item_stage_fraction(
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
                _write_status(job_dir, status)
                append_log(log_path, f"[{now_iso()}] {stage_name}: {input_item.original_path}")

            try:
                item_warnings = _process_one_item(
                    job_dir=job_dir,
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
                        "job_id": request.job_id,
                        "run_dir": str(job_dir),
                        "audio_id": manifest_item.media_id,
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
                status.videos_done += 1
                append_log(log_path, f"[{now_iso()}] Completed: {input_item.original_path}")
            except JobDeletionRequested:
                raise
            except Exception as exc:
                manifest_item.status = "failed"
                status.videos_failed += 1
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
            status.current_media_elapsed_sec = round(monotonic() - item_started, 3)
            status.current_stage_elapsed_sec = 0.0
            status.progress_percent = _completed_progress_percent(
                processed_duration_sec=status.processed_duration_sec,
                total_duration_sec=status.total_duration_sec,
                total_items=max(len(manifest_items), 1),
                completed_items=status.videos_done + status.videos_skipped + status.videos_failed,
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
            _write_manifest(job_dir, request.job_id, manifest_items)
            _write_status(job_dir, status)

        if appended_catalog_rows:
            append_catalog_rows(Path(request.output_root_path), appended_catalog_rows)

        _raise_if_delete_requested(job_dir, "finalize")
        status.current_media = None
        status.current_media_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0

        has_failures = status.videos_failed > 0
        result.state = "failed" if has_failures else "completed"
        result.processed_count = status.videos_done
        result.skipped_count = status.videos_skipped
        result.error_count = status.videos_failed
        result.batch_count = 0
        result.timeline_index_path = None
        result.warnings = warnings
        _write_result(job_dir, result)

        status.state = "failed" if has_failures else "completed"
        status.current_stage = "failed" if has_failures else "completed"
        status.message = "Job finished with errors." if has_failures else "Job completed."
        status.warnings = warnings
        status.current_media = None
        status.current_media_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0
        status.progress_percent = 100.0
        status.completed_at = now_iso()
        _write_status(job_dir, status)
        append_log(
            log_path,
            f"[{now_iso()}] Job {'finished with errors' if has_failures else 'completed'} with {status.videos_done} processed, {status.videos_skipped} skipped, {status.videos_failed} failed.",
        )
        return True
    except JobDeletionRequested as exc:
        delete_requested = True
        append_log(log_path, f"[{now_iso()}] Job canceled for deletion: {exc}")
        status.state = "canceled"
        status.current_stage = "canceled"
        status.message = "Deletion requested. Job canceled."
        status.warnings = warnings
        status.current_media = None
        status.current_media_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = 0.0
        status.progress_percent = max(status.progress_percent, 1.0)
        status.completed_at = now_iso()
        _write_status(job_dir, status)
        result.state = "canceled"
        result.processed_count = status.videos_done
        result.skipped_count = status.videos_skipped
        result.error_count = status.videos_failed
        result.warnings = warnings
        _write_result(job_dir, result)
        return True
    except Exception as exc:
        append_log(log_path, f"[{now_iso()}] Job failed: {exc}")
        append_log(log_path, traceback.format_exc())
        status.state = "failed"
        status.current_stage = "failed"
        status.message = str(exc)
        status.warnings = warnings
        status.current_stage_elapsed_sec = 0.0
        status.progress_percent = max(status.progress_percent, 1.0)
        status.completed_at = now_iso()
        _write_status(job_dir, status)
        result.state = "failed"
        result.processed_count = status.videos_done
        result.skipped_count = status.videos_skipped
        result.error_count = status.videos_failed + 1
        result.warnings = warnings + [tail_text(log_path, max_lines=30)]
        _write_result(job_dir, result)
        return True
    finally:
        if lock_acquired:
            _release_job_lock(job_dir)
        if delete_requested:
            _delete_job_dir(job_dir, request)

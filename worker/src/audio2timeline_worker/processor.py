from __future__ import annotations

import json
import threading
import traceback
from pathlib import Path
from time import monotonic
from typing import Any, Callable

from .audio_features import analyze_audio, write_speaker_summary
from .catalog import append_catalog_rows, catalog_key, load_catalog
from .contracts import JobRequest, JobResult, JobStatus, ManifestItem
from .eta import build_eta_predictor, estimate_remaining_seconds
from .ffmpeg_utils import extract_audio, probe_audio
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
from .settings import load_settings
from .timeline import render_timeline
from .transcribe import transcribe_audio

_ITEM_STAGE_BOUNDS: dict[str, tuple[float, float]] = {
    "extract_audio": (0.0, 0.16),
    "transcribe": (0.16, 0.76),
    "analyze_audio": (0.76, 0.94),
    "timeline_render": (0.94, 1.0),
}


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


def _resolve_duplicate_timeline_path(duplicate: dict[str, Any] | None) -> Path | None:
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
        candidate = Path(str(run_dir)) / "media" / str(media_id) / "timeline" / "timeline.md"
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
    if stage_name == "transcribe":
        factor = 0.25 if compute_mode == "gpu" else 1.20
        ceiling = 180.0 if compute_mode == "gpu" else 900.0
        return max(4.0, min(ceiling, safe_duration * factor))
    if stage_name == "analyze_audio":
        return max(2.0, min(120.0, safe_duration * 0.12))
    if stage_name == "timeline_render":
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
    run_info = "\n".join(
        [
            "# Run Info",
            "",
            f"- Job ID: `{request.job_id}`",
            f"- Created At: `{request.created_at}`",
            f"- Profile: `{request.profile}`",
            f"- Compute Mode: `{request.compute_mode}`",
            f"- Processing Quality: `{request.processing_quality}`",
            f"- Input Count: `{len(request.input_items)}`",
            f"- Reprocess Duplicates: `{request.reprocess_duplicates}`",
            "",
            "This run uses file-based coordination between the ASP.NET Core web app and the Python worker.",
            "",
        ]
    )
    transcription_info = "\n".join(
        [
            "# Transcription Info",
            "",
            f"- Audio transcription: `{request.transcription_backend}` with `{request.transcription_model_id}`, `ja`, requested `{request.compute_mode}`",
            f"- Diarization enabled: `{request.diarization_enabled}`",
            f"- Diarization model: `{request.diarization_model_id or ''}`",
            f"- VAD backend: `{request.vad_backend}` / `{request.vad_model_id}`",
            f"- Pipeline version: `{request.pipeline_version}`",
            f"- Conversion signature: `{request.conversion_signature}`",
            "- Notes:",
            "  - `raw` outputs are preserved.",
            "  - Speaker summary and audio feature summary are emitted as sidecar markdown files.",
            "  - Optional audio analysis does not fail the main transcription job.",
            "",
        ]
    )
    notice = "\n".join(
        [
            "# Notice",
            "",
            "- This run is optimized for local processing, not cloud transcription.",
            "- Model downloads may happen on first use and are cached afterward.",
            "- If diarization prerequisites are missing, the worker continues without speaker separation.",
            "- Timeline timestamps are based on the original audio time.",
            "",
        ]
    )
    write_text(job_dir / "RUN_INFO.md", run_info)
    write_text(job_dir / "TRANSCRIPTION_INFO.md", transcription_info)
    write_text(job_dir / "NOTICE.md", notice)


def _resolve_input_path(item: Any) -> Path:
    if item.uploaded_path:
        return Path(item.uploaded_path)
    return Path(item.original_path)


def _make_media_id(item: Any, file_hash: str) -> str:
    stem = slugify(Path(item.display_name or Path(item.original_path).stem).stem)
    return f"{stem}-{file_hash[:8] or short_id()}"


def _collect_pending_jobs() -> list[Path]:
    return _collect_jobs_by_state("pending")


def _collect_running_jobs() -> list[Path]:
    return _collect_jobs_by_state("running")


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
            if not _request_path(candidate).exists():
                continue
            status = _load_status(candidate)
            if status.state.lower() in target_states:
                rows.append(candidate)
    return rows


def _llm_export(job_dir: Path, processed_items: list[ManifestItem]) -> tuple[int, Path | None]:
    llm_dir = ensure_dir(job_dir / "llm")
    rows: list[dict[str, Any]] = []
    batch_contents: list[str] = []
    current_batch: list[str] = []
    current_size = 0
    max_batch_chars = 120_000

    for item in processed_items:
        if item.status != "completed" or not item.media_id:
            continue
        timeline_path = job_dir / "media" / item.media_id / "timeline" / "timeline.md"
        if not timeline_path.exists():
            continue
        row = {
            "job_id": job_dir.name,
            "audio_id": item.media_id,
            "original_path": item.original_path,
            "timeline_path": str(timeline_path),
            "duration_seconds": item.duration_seconds,
            "source_hash": item.sha256,
            "conversion_signature": item.conversion_signature,
        }
        rows.append(row)
        timeline_text = timeline_path.read_text(encoding="utf-8", errors="replace").strip()
        block = "\n".join(
            [
                f"# Audio: {item.media_id}",
                f"- Source: `{item.original_path}`",
                "",
                timeline_text,
                "",
            ]
        )
        if current_batch and current_size + len(block) > max_batch_chars:
            batch_contents.append("\n".join(current_batch).strip() + "\n")
            current_batch = []
            current_size = 0
        current_batch.append(block)
        current_size += len(block)

    if current_batch:
        batch_contents.append("\n".join(current_batch).strip() + "\n")

    index_path: Path | None = None
    if rows:
        index_path = llm_dir / "timeline_index.jsonl"
        index_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
    for idx, content in enumerate(batch_contents, start=1):
        write_text(llm_dir / f"batch-{idx:03d}.md", content)

    return len(batch_contents), index_path


def _process_one_item(
    *,
    job_dir: Path,
    request: JobRequest,
    item: Any,
    manifest_item: ManifestItem,
    on_stage: Callable[[str, str], None] | None = None,
) -> list[str]:
    source_path = _resolve_input_path(item)
    media_dir = ensure_dir(job_dir / "media" / str(manifest_item.media_id))
    audio_dir = ensure_dir(media_dir / "audio")
    transcript_dir = ensure_dir(media_dir / "transcript")
    analysis_dir = ensure_dir(media_dir / "analysis")
    timeline_dir = ensure_dir(media_dir / "timeline")

    source_info = {
        "job_id": request.job_id,
        "audio_id": manifest_item.media_id,
        "input_id": item.input_id,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "original_path": item.original_path,
        "resolved_path": str(source_path),
        "display_name": item.display_name,
        "size_bytes": manifest_item.size_bytes,
        "duration_seconds": manifest_item.duration_seconds,
        "source_hash": manifest_item.sha256,
        "conversion_signature": manifest_item.conversion_signature,
        "captured_at": manifest_item.captured_at,
        "container_name": manifest_item.container_name,
        "extension": manifest_item.extension,
        "audio_codec": manifest_item.audio_codec,
        "audio_channels": manifest_item.audio_channels,
        "audio_sample_rate": manifest_item.audio_sample_rate,
        "bitrate": manifest_item.bitrate,
        "model_id": manifest_item.model_id,
        "pipeline_version": manifest_item.pipeline_version,
    }
    write_json_atomic(media_dir / "source.json", source_info)

    normalized_audio_path = audio_dir / "normalized.wav"

    if on_stage:
        on_stage("extract_audio", "Normalizing audio.")
    extract_audio(source_path, normalized_audio_path)
    cut_map: list[dict[str, float]] = []
    write_json_atomic(audio_dir / "cut_map.json", cut_map)

    if on_stage:
        on_stage("transcribe", "Running faster-whisper transcription.")
    transcript_payload = transcribe_audio(
        source_name=item.display_name,
        audio_path=normalized_audio_path,
        transcript_dir=transcript_dir,
        cut_map=cut_map,
        compute_mode=request.compute_mode,
        processing_quality=request.processing_quality,
    )
    if on_stage:
        on_stage("analyze_audio", "Computing audio summaries.")
    speaker_summary = write_speaker_summary(
        source_name=item.display_name,
        output_dir=analysis_dir,
        transcript_payload=transcript_payload,
    )
    audio_feature_summary = analyze_audio(
        source_name=item.display_name,
        audio_path=normalized_audio_path,
        duration_seconds=manifest_item.duration_seconds,
        transcript_payload=transcript_payload,
        output_dir=analysis_dir,
    )
    manifest_item.pause_summary = audio_feature_summary.get("pause_summary", {})
    manifest_item.loudness_summary = audio_feature_summary.get("loudness_summary", {})
    manifest_item.speaking_rate_summary = audio_feature_summary.get("speaking_rate_summary", {})
    manifest_item.pitch_summary = audio_feature_summary.get("pitch_summary", {})
    manifest_item.speaker_confidence_summary = audio_feature_summary.get(
        "speaker_confidence_summary", {}
    )
    manifest_item.optional_voice_feature_summary = audio_feature_summary.get(
        "optional_voice_feature_summary", {}
    )
    if on_stage:
        on_stage("timeline_render", "Rendering timeline markdown.")
    render_timeline(
        output_path=timeline_dir / "timeline.md",
        source_info=source_info,
        transcript_payload=transcript_payload,
        speaker_summary=speaker_summary,
        audio_feature_summary=audio_feature_summary,
    )
    return []


def process_job(job_dir: Path | None = None) -> bool:
    if job_dir is None:
        if _collect_running_jobs():
            return False
        pending = _collect_pending_jobs()
        if not pending:
            return False
        job_dir = pending[0]

    job_dir = job_dir.resolve()
    if not _request_path(job_dir).exists():
        return False

    log_path = _job_log_path(job_dir)
    request = _load_request(job_dir)
    _write_support_docs(job_dir, request)

    status = _load_status(job_dir)
    status.job_id = request.job_id
    status.state = "running"
    status.current_stage = "preflight"
    status.message = "Preparing job."
    status.current_stage_elapsed_sec = 0.0
    status.progress_percent = max(status.progress_percent, 1.0)
    status.started_at = status.started_at or now_iso()
    _write_status(job_dir, status)

    result = JobResult(
        job_id=request.job_id,
        state="running",
        run_dir=str(job_dir),
        output_root_id=request.output_root_id,
        output_root_path=request.output_root_path,
    )
    _write_result(job_dir, result)

    started = monotonic()
    warnings: list[str] = []
    compute_mode = str(request.compute_mode or "cpu").lower()
    catalog = load_catalog(Path(request.output_root_path))
    manifest_items: list[ManifestItem] = []
    appended_catalog_rows: list[dict[str, Any]] = []

    try:
        append_log(log_path, f"[{now_iso()}] Starting job {request.job_id}")
        for index, input_item in enumerate(request.input_items, start=1):
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
            media_probe = probe_audio(source_path)
            file_hash = sha256_file(source_path)
            duplicate = catalog.get(catalog_key(file_hash, request.conversion_signature))
            duplicate_status = "new"
            duplicate_of = None
            duplicate_timeline_path = _resolve_duplicate_timeline_path(duplicate)
            if duplicate_timeline_path is not None:
                duplicate_of = str(
                    duplicate.get("audio_id")
                    or duplicate.get("media_id")
                    or duplicate_timeline_path
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
                    duration_seconds=float(media_probe["duration_seconds"]),
                    source_hash=file_hash,
                    conversion_signature=request.conversion_signature,
                    duplicate_status=duplicate_status,
                    duplicate_of=duplicate_of or None,
                    audio_id=_make_media_id(input_item, file_hash),
                    status="queued",
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
            processing_quality=request.processing_quality,
        )
        append_log(
            log_path,
            f"[{now_iso()}] ETA history loaded: {eta_predictor.sample_count} sample(s) "
            f"for compute_mode={request.compute_mode}, quality={request.processing_quality}.",
        )

        completed_items: list[ManifestItem] = []
        for index, (input_item, manifest_item) in enumerate(
            zip(request.input_items, manifest_items, strict=False), start=1
        ):
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
                        "original_path": manifest_item.original_path,
                        "duration_seconds": manifest_item.duration_seconds,
                        "timeline_path": str(
                            job_dir
                            / "media"
                            / str(manifest_item.media_id)
                            / "timeline"
                            / "timeline.md"
                        ),
                        "created_at": now_iso(),
                    }
                )
                status.videos_done += 1
                append_log(log_path, f"[{now_iso()}] Completed: {input_item.original_path}")
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

        status.current_stage = "llm_export"
        status.message = "Building timeline batches."
        status.current_media = None
        status.current_media_elapsed_sec = 0.0
        status.current_stage_elapsed_sec = 0.0
        status.estimated_remaining_sec = _stage_expected_seconds("llm_export", 1.0, compute_mode)
        llm_export_started = monotonic()
        status.progress_percent = 95.0
        _write_status(job_dir, status)
        batch_count, timeline_index_path = _llm_export(job_dir, completed_items)

        has_failures = status.videos_failed > 0
        result.state = "failed" if has_failures else "completed"
        result.processed_count = status.videos_done
        result.skipped_count = status.videos_skipped
        result.error_count = status.videos_failed
        result.batch_count = batch_count
        result.timeline_index_path = str(timeline_index_path) if timeline_index_path else None
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
        status.progress_percent = _overall_progress_percent(
            processed_duration_sec=status.processed_duration_sec,
            total_duration_sec=status.total_duration_sec,
            current_stage="llm_export",
            current_stage_elapsed_sec=monotonic() - llm_export_started,
            current_media_duration_sec=0.0,
            compute_mode=compute_mode,
        )
        status.progress_percent = 100.0
        status.completed_at = now_iso()
        _write_status(job_dir, status)
        append_log(
            log_path,
            f"[{now_iso()}] Job {'finished with errors' if has_failures else 'completed'} with {status.videos_done} processed, {status.videos_skipped} skipped, {status.videos_failed} failed.",
        )
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

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import uuid4

from .catalog import catalog_key, load_catalog, load_catalog_rows, normalize_file_identity
from .contracts import InputItem, RunRequest, RunResult, RunStatus
from .discovery import discover_audio
from .fs_utils import ensure_dir, now_iso, write_text
from .hashing import sha256_file
from .pagination import list_payload
from .vad_profile import resolve_vad_profile
from .signature import (
    DIARIZATION_MODEL_ID,
    PIPELINE_VERSION,
    TRANSCRIPTION_BACKEND_NAME,
    VAD_BACKEND,
    VAD_MODEL_ID,
    build_conversion_signature,
    normalize_compute_mode,
    resolve_transcription_model_id,
)
from .settings import (
    appdata_root,
    configured_path,
    load_huggingface_token,
    load_settings,
    settings_token,
    supported_audio_extensions,
)

_FIXED_VAD_PROFILE = resolve_vad_profile(None)
_FINAL_TIMELINE_FILE = "timeline.json"


def _metadata_root(output_root_path: Path) -> Path:
    try:
        normalized = str(output_root_path.resolve(strict=False))
    except Exception:
        normalized = str(output_root_path)
    key = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()[:16]
    return appdata_root() / key


def _runs_root(output_root_path: Path) -> Path:
    return _metadata_root(output_root_path) / "runs"


def _allowed_extensions(settings: dict[str, Any]) -> set[str]:
    return {
        ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
        for ext in supported_audio_extensions()
        if str(ext).strip()
    }


def _enabled_output_root(
    settings: dict[str, Any], output_root_id: str | None = None
) -> dict[str, Any]:
    if output_root_id and str(output_root_id).lower() != "master":
        raise ValueError("Only the master output root is supported.")
    root = settings.get("outputRoot")
    if isinstance(root, str) and root.strip():
        return {"id": "master", "path": root.strip()}
    raise ValueError("No master output root is configured.")


def _enabled_input_roots(settings: dict[str, Any]) -> list[dict[str, Any]]:
    roots: list[dict[str, Any]] = []
    for root in settings.get("inputRoots", []):
        root_path = root.strip() if isinstance(root, str) else ""
        if not root_path:
            continue
        roots.append({"id": root_path, "path": root_path})
    return roots


def _source_root_for_id(settings: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    for root in _enabled_input_roots(settings):
        if str(root.get("id") or "").lower() == str(source_id or "").lower():
            return root
    return None


def _relative_path_label(path: Path, root_path: Path | None = None) -> str:
    try:
        if root_path is not None:
            return path.resolve().relative_to(root_path.resolve()).as_posix()
    except ValueError:
        pass
    try:
        return path.resolve().as_posix()
    except Exception:
        return path.as_posix()


def _source_file_identity(source_id: str, relative_path: str) -> str:
    source = str(source_id or "local").strip() or "local"
    relative = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    return f"{source}::{relative}"


def _display_path_from_root(root_path: str, relative_path: str, fallback: Path) -> str:
    root_text = str(root_path or "").strip()
    relative_text = str(relative_path or "").strip().replace("\\", "/").lstrip("/")
    if not root_text:
        return str(fallback)
    if not relative_text:
        return root_text
    parts = [part for part in relative_text.split("/") if part]
    if _looks_like_windows_path(root_text):
        return str(PureWindowsPath(root_text, *parts))
    return str(Path(root_text, *parts))


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", value)) or "\\" in value


def _iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat()


def app_config_from_settings(settings: dict[str, Any]) -> Any:
    from .config import AppConfig, SourceDirectory

    return AppConfig(
        project_name="TimelineForAudio",
        source_directories=[
            SourceDirectory(
                name=str(root.get("id") or "source"),
                path=str(configured_path(str(root.get("path") or ""))),
                recursive=bool(root.get("recursive", True)),
            )
            for root in _enabled_input_roots(settings)
        ],
        output_root=str(configured_path(str(_enabled_output_root(settings).get("path") or ""))),
        audio_extensions=sorted(_allowed_extensions(settings)),
    )


def _iter_audio_files(directory: Path, allowed_extensions: set[str]) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        [
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in allowed_extensions
        ],
        key=lambda item: str(item).lower(),
    )


def collect_input_items(
    *,
    settings: dict[str, Any],
    files: list[Path] | None = None,
    directories: list[Path] | None = None,
    source_ids: list[str] | None = None,
) -> list[InputItem]:
    allowed_extensions = _allowed_extensions(settings)
    rows: list[InputItem] = []
    seen_paths: set[str] = set()

    def add_path(
        path: Path,
        source_kind: str,
        source_id: str,
        source_root_path: Path | None = None,
    ) -> None:
        original_path = str(path)
        resolved = configured_path(path).resolve()
        key = str(resolved).lower()
        if key in seen_paths:
            return
        if not resolved.exists() or not resolved.is_file():
            raise ValueError(f"Input file was not found: {resolved}")
        if resolved.suffix.lower() not in allowed_extensions:
            return
        seen_paths.add(key)
        size_bytes = resolved.stat().st_size
        relative_path = _relative_path_label(resolved, source_root_path)
        rows.append(
            InputItem(
                input_id=f"{source_kind[:4]}-{len(rows) + 1:04d}",
                source_kind=source_kind,
                source_id=source_id,
                original_path=original_path,
                display_name=resolved.name,
                size_bytes=size_bytes,
                source_relative_path=relative_path,
                source_file_identity=_source_file_identity(source_id, relative_path),
            )
        )

    for file_path in files or []:
        add_path(file_path, "local_file", "local")

    for directory in directories or []:
        resolved_directory = configured_path(directory).resolve()
        if not resolved_directory.exists() or not resolved_directory.is_dir():
            raise ValueError(f"Input directory was not found: {resolved_directory}")
        for file_path in _iter_audio_files(resolved_directory, allowed_extensions):
            add_path(
                file_path,
                "local_directory",
                str(resolved_directory),
                source_root_path=resolved_directory,
            )

    if source_ids:
        selected_ids = {value.lower() for value in source_ids}
        config = app_config_from_settings(settings)
        discovered = discover_audio(config)
        for row in discovered.get("audio_files", []):
            source_name = str(row.get("source_name") or "")
            source_root = next(
                (
                    root
                    for root in _enabled_input_roots(settings)
                    if str(root.get("id") or "").lower() == source_name.lower()
                ),
                None,
            )
            if source_root is None:
                continue
            if source_name.lower() not in selected_ids:
                continue
            root_path = configured_path(str(source_root.get("path") or "")).resolve()
            add_path(
                Path(str(row["path"])),
                "mounted_root",
                str(source_root.get("id") or source_name),
                source_root_path=root_path,
            )

    return rows


def list_runs(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    rows: list[dict[str, Any]] = []
    for root in _enabled_output_root_list(settings):
        output_path = configured_path(str(root["path"]))
        if not output_path.exists():
            continue
        for run_dir in _iter_run_dirs(output_path):
            request_path = run_dir / "request.json"
            status_path = run_dir / "status.json"
            manifest_path = run_dir / "manifest.json"
            if not request_path.exists() or not status_path.exists():
                continue
            request = json.loads(request_path.read_text(encoding="utf-8-sig", errors="replace"))
            status = json.loads(status_path.read_text(encoding="utf-8-sig", errors="replace"))
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8-sig", errors="replace"))
                if manifest_path.exists()
                else {"items": []}
            )
            items = manifest.get("items", [])
            rows.append(
                {
                    "run_id": request.get("run_id", run_dir.name),
                    "run_dir": str(run_dir),
                    "state": status.get("state", "unknown"),
                    "current_stage": status.get("current_stage", ""),
                    "items_total": status.get("items_total", status.get("videos_total", 0)),
                    "items_done": status.get("items_done", status.get("videos_done", 0)),
                    "items_skipped": status.get("items_skipped", status.get("videos_skipped", 0)),
                    "items_failed": status.get("items_failed", status.get("videos_failed", 0)),
                    "updated_at": status.get("updated_at"),
                    "created_at": request.get("created_at"),
                    "total_size_bytes": sum(int(item.get("size_bytes", 0)) for item in items),
                    "total_duration_sec": sum(
                        float(item.get("duration_seconds", 0.0)) for item in items
                    ),
                }
            )
    return rows


def _enabled_output_root_list(settings: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return [_enabled_output_root(settings)]
    except ValueError:
        return []


def get_active_run(settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for row in list_runs(settings):
        if str(row.get("state", "")).lower() in {"pending", "running"}:
            return row
    return None


def find_run_dir(run_id: str, settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    for root in _enabled_output_root_list(settings):
        output_path = configured_path(str(root["path"]))
        for candidate in (
            _runs_root(output_path) / run_id,
            output_path / run_id,
        ):
            if candidate.exists():
                return candidate
    raise ValueError(f"Run not found: {run_id}")


def create_run(
    *,
    settings: dict[str, Any] | None = None,
    input_items: list[InputItem],
    output_root_id: str | None = None,
    reprocess_duplicates: bool = False,
) -> tuple[str, Path]:
    settings = settings or load_settings()
    if not input_items:
        raise ValueError("No input audio files were selected.")

    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = configured_path(str(output_root["path"]))
    ensure_dir(output_root_path)
    ensure_dir(_runs_root(output_root_path))

    run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    run_dir = _runs_root(output_root_path) / run_id
    ensure_dir(run_dir / "work")
    ensure_dir(run_dir / "logs")

    diarization_enabled = True
    compute_mode = normalize_compute_mode(settings.get("computeMode"))
    request = RunRequest(
        schema_version=1,
        run_id=run_id,
        created_at=now_iso(),
        output_root_id=str(output_root.get("id") or "runs"),
        output_root_path=str(output_root_path),
        profile="quality-first",
        compute_mode=compute_mode,
        pipeline_version=PIPELINE_VERSION,
        conversion_signature=build_conversion_signature(
            compute_mode=settings.get("computeMode"),
            diarization_enabled=diarization_enabled,
            vad_profile=_FIXED_VAD_PROFILE,
        ),
        transcription_backend=TRANSCRIPTION_BACKEND_NAME,
        transcription_model_id=resolve_transcription_model_id(),
        diarization_enabled=diarization_enabled,
        diarization_model_id=DIARIZATION_MODEL_ID,
        vad_backend=VAD_BACKEND,
        vad_model_id=VAD_MODEL_ID,
        vad_profile=_FIXED_VAD_PROFILE,
        reprocess_duplicates=reprocess_duplicates,
        token_enabled=bool(load_huggingface_token()),
        input_items=input_items,
    )
    status = RunStatus(
        run_id=run_id,
        state="pending",
        current_stage="queued",
        message="Queued for worker pickup.",
        items_total=len(input_items),
        updated_at=now_iso(),
    )
    result = RunResult(
        run_id=run_id,
        state="pending",
        run_dir=str(run_dir),
        output_root_id=str(output_root.get("id") or "runs"),
        output_root_path=str(output_root_path),
    )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "generated_at": now_iso(),
        "items": [],
    }

    (run_dir / "request.json").write_text(
        json.dumps(request.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "status.json").write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_text(run_dir / "RUN_INFO.md", "# Run Info\n\nPending worker pickup.\n")
    write_text(run_dir / "NOTICE.md", "# Notice\n\nPending worker pickup.\n")

    return run_id, run_dir


def _artifact_path_from_catalog_row(row: dict[str, Any] | None) -> Path | None:
    if not row:
        return None
    direct_path = row.get("artifact_path")
    if direct_path:
        candidate = Path(str(direct_path))
        if candidate.exists():
            return candidate
    media_dir = _media_dir_from_catalog_row(row)
    if media_dir is None:
        return None
    for candidate in (
        media_dir / _FINAL_TIMELINE_FILE,
    ):
        if candidate.exists():
            return candidate
    return None


def item_id_from_catalog_row(row: dict[str, Any]) -> str:
    media_id = str(row.get("audio_id") or row.get("media_id") or "").strip()
    if media_id:
        return media_id
    source_hash = str(row.get("source_hash") or row.get("sha256") or "").strip()
    conversion_signature = str(row.get("conversion_signature") or "").strip()
    source_file_identity = str(row.get("source_file_identity") or "").strip()
    run_id = str(row.get("run_id") or row.get("job_id") or "").strip()
    seed = "::".join(
        part
        for part in (
            normalize_file_identity(source_file_identity),
            source_hash.lower(),
            conversion_signature.lower(),
            run_id,
            media_id,
        )
        if part
    )
    if not seed:
        seed = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return f"item-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:12]}"


def _media_dir_from_catalog_row(row: dict[str, Any] | None) -> Path | None:
    if not row:
        return None
    item_dir = row.get("item_dir") or row.get("media_dir")
    if item_dir:
        return Path(str(item_dir))
    run_dir = row.get("run_dir")
    media_id = row.get("audio_id") or row.get("media_id")
    if not run_dir or not media_id:
        return None
    return Path(str(run_dir)) / "media" / str(media_id)


def _safe_media_dir_from_catalog_row(
    row: dict[str, Any],
    *,
    output_root_path: Path,
) -> Path | None:
    media_dir = _media_dir_from_catalog_row(row)
    run_dir = row.get("run_dir")
    if media_dir is None:
        return None
    try:
        resolved_output = output_root_path.resolve(strict=False)
        resolved_media = media_dir.resolve(strict=False)
        resolved_media.relative_to(resolved_output)
    except Exception:
        return None
    if resolved_media == resolved_output or ".timeline-for-audio" in resolved_media.parts:
        return None
    if run_dir:
        try:
            resolved_run = Path(str(run_dir)).resolve(strict=False)
            resolved_media_root = (resolved_run / "media").resolve(strict=False)
            if resolved_media == resolved_media_root:
                return None
            resolved_media.relative_to(resolved_media_root)
        except Exception:
            pass
    return resolved_media


def _catalog_rows_for_output_root(output_root_path: Path) -> list[tuple[str, dict[str, Any]]]:
    rows = load_catalog_rows(output_root_path)
    return [(json.dumps(row, ensure_ascii=False, sort_keys=True), row) for row in rows]


def _source_info_from_media_dir(media_dir: Path | None) -> dict[str, Any]:
    if media_dir is None:
        return {}
    for candidate in (
        media_dir / "source" / "source-record.json",
        media_dir / "source.json",
    ):
        if not candidate.exists():
            continue
        try:
            return json.loads(candidate.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return {}
    for timeline_path in (
        media_dir / _FINAL_TIMELINE_FILE,
    ):
        if not timeline_path.exists():
            continue
        try:
            payload = json.loads(timeline_path.read_text(encoding="utf-8-sig", errors="replace"))
        except (OSError, json.JSONDecodeError):
            return {}
        source = payload.get("source")
        if isinstance(source, dict):
            return source
    return {}


def list_items(
    *,
    settings: dict[str, Any] | None = None,
    output_root_id: str | None = None,
) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = configured_path(str(output_root["path"])).resolve()
    rows: list[dict[str, Any]] = []
    for _, row in _catalog_rows_for_output_root(output_root_path):
        media_dir = _safe_media_dir_from_catalog_row(row, output_root_path=output_root_path)
        artifact_path = _artifact_path_from_catalog_row(row)
        media_id = str(row.get("audio_id") or row.get("media_id") or "")
        source_info = _source_info_from_media_dir(media_dir)
        timeline_summary = _timeline_summary_from_artifact(artifact_path)
        source_relative_path = str(row.get("source_relative_path") or "")
        created_at = str(row.get("created_at") or "")
        updated_at = _item_updated_at(row=row, artifact_path=artifact_path, media_dir=media_dir)
        source_display_name = (
            str(source_info.get("display_name") or "").strip()
            or Path(source_relative_path).name
            or Path(str(source_info.get("original_path") or "")).name
            or media_id
        )
        rows.append(
            {
                "item_id": item_id_from_catalog_row(row),
                "media_id": media_id,
                "run_id": row.get("run_id") or row.get("job_id"),
                "run_dir": row.get("run_dir"),
                "source_id": row.get("source_id"),
                "source_relative_path": source_relative_path,
                "source_file_identity": row.get("source_file_identity"),
                "source_file_name": source_display_name,
                "source_hash": row.get("source_hash") or row.get("sha256"),
                "conversion_signature": row.get("conversion_signature"),
                "duration_sec": row.get("duration_seconds") or row.get("duration_sec"),
                "created_at": created_at,
                "updated_at": updated_at,
                "status": "available" if artifact_path is not None else "missing_artifact",
                "artifact_path": str(artifact_path) if artifact_path is not None else "",
                "media_dir": str(media_dir) if media_dir is not None else "",
                "turn_count": int(timeline_summary["turn_count"]),
                "speaker_count": int(timeline_summary["speaker_count"]),
            }
        )
    rows.sort(
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("item_id") or ""),
        ),
        reverse=True,
    )
    return rows


def list_items_page(
    *,
    settings: dict[str, Any] | None = None,
    output_root_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    rows = list_items(settings=settings, output_root_id=output_root_id)
    return list_payload(
        key="items",
        count_key="item_count",
        total_key="total_items",
        returned_key="returned_items",
        rows=rows,
        page=page,
        page_size=page_size,
        sort_fields=["updated_at", "created_at", "item_id"],
    )


def _item_updated_at(
    *,
    row: dict[str, Any],
    artifact_path: Path | None,
    media_dir: Path | None,
) -> str:
    candidates: list[float] = []
    for path in (
        artifact_path,
        media_dir / "convert_info.json" if media_dir is not None else None,
        media_dir if media_dir is not None else None,
    ):
        if path is None or not path.exists():
            continue
        try:
            candidates.append(path.stat().st_mtime)
        except OSError:
            continue
    if candidates:
        return _iso_from_timestamp(max(candidates))
    return str(row.get("updated_at") or row.get("created_at") or "")


def remove_items(
    *,
    item_ids: list[str],
    settings: dict[str, Any] | None = None,
    output_root_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = settings or load_settings()
    requested: dict[str, str] = {}
    for value in item_ids:
        normalized = str(value or "").strip().lower()
        if normalized:
            requested[normalized] = str(value)
    if not requested:
        raise ValueError("At least one item id is required.")

    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = configured_path(str(output_root["path"])).resolve()
    media_dirs: dict[str, Path] = {}
    unsafe_media_dirs: list[str] = []
    removed_rows: list[dict[str, Any]] = []
    matched_item_ids: set[str] = set()

    for _, row in _catalog_rows_for_output_root(output_root_path):
        item_id = item_id_from_catalog_row(row).lower()
        if item_id not in requested:
            continue

        matched_item_ids.add(item_id)
        media_dir = _safe_media_dir_from_catalog_row(row, output_root_path=output_root_path)
        if media_dir is not None:
            media_dirs[str(media_dir)] = media_dir
        else:
            raw_media_dir = _media_dir_from_catalog_row(row)
            if raw_media_dir is not None:
                unsafe_media_dirs.append(str(raw_media_dir))
        removed_rows.append(
            {
                "item_id": item_id_from_catalog_row(row),
                "source_file_identity": row.get("source_file_identity"),
                "run_id": row.get("run_id") or row.get("job_id"),
                "media_id": row.get("audio_id") or row.get("media_id"),
                "run_dir": row.get("run_dir"),
            }
        )

    missing = [
        original
        for normalized, original in requested.items()
        if normalized not in matched_item_ids
    ]
    media_dir_rows = sorted(media_dirs.values(), key=lambda item: str(item).lower())

    if removed_rows and not dry_run:
        for media_dir in media_dir_rows:
            shutil.rmtree(media_dir, ignore_errors=True)

    return {
        "dry_run": dry_run,
        "requested_item_ids": list(requested.values()),
        "matched_count": len(matched_item_ids),
        "missing_item_ids": missing,
        "catalog_rows_removed": len(removed_rows),
        "media_dirs_removed": 0 if dry_run else len(media_dir_rows),
        "media_dirs": [str(path) for path in media_dir_rows],
        "unsafe_media_dirs": unsafe_media_dirs,
        "removed_rows": removed_rows,
    }


def build_items_archive(
    *,
    item_ids: list[str],
    settings: dict[str, Any] | None = None,
    output_root_id: str | None = None,
    output: Path | None = None,
) -> Path:
    settings = settings or load_settings()
    requested = {str(value or "").strip().lower(): str(value) for value in item_ids if str(value or "").strip()}
    if not requested:
        raise ValueError("At least one item id is required.")

    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = configured_path(str(output_root["path"])).resolve()
    catalog_rows = [row for _, row in _catalog_rows_for_output_root(output_root_path)]
    matched_rows = [
        row for row in catalog_rows if item_id_from_catalog_row(row).lower() in requested
    ]
    matched_ids = {item_id_from_catalog_row(row).lower() for row in matched_rows}
    missing = [
        original for normalized, original in requested.items() if normalized not in matched_ids
    ]
    if missing:
        raise ValueError(f"Item not found: {', '.join(missing)}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_base = (
        output.with_suffix("") if output is not None and output.suffix.lower() == ".zip" else output
    )
    if archive_base is None:
        downloads_root = Path(
            os.getenv("TIMELINE_FOR_AUDIO_DOWNLOADS_ROOT", str(output_root_path))
        )
        archive_base = downloads_root / f"timelineforaudio-items-{timestamp}"
    archive_base = archive_base.resolve()
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()

    staging_root = Path(
        tempfile.mkdtemp(prefix=f"{archive_base.name}-export-", dir=str(archive_base.parent))
    )
    try:
        items_manifest: list[dict[str, Any]] = []
        for row in matched_rows:
            artifact_path = _artifact_path_from_catalog_row(row)
            if artifact_path is None:
                continue
            media_dir = _safe_media_dir_from_catalog_row(row, output_root_path=output_root_path)
            source_info = _source_info_from_media_dir(media_dir)
            media_id = str(row.get("audio_id") or row.get("media_id") or "")
            item_id = item_id_from_catalog_row(row)
            export_item_dir = staging_root / "items" / item_id
            export_item_dir.mkdir(parents=True, exist_ok=True)
            destination = export_item_dir / _FINAL_TIMELINE_FILE
            destination.write_text(
                artifact_path.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            conversion_info_path = (
                media_dir / "convert_info.json" if media_dir is not None else None
            )
            exported_conversion_path = ""
            if conversion_info_path is not None and conversion_info_path.exists():
                conversion_destination = export_item_dir / "convert_info.json"
                conversion_destination.write_text(
                    conversion_info_path.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
                exported_conversion_path = f"items/{item_id}/convert_info.json"
            items_manifest.append(
                {
                    "item_id": item_id,
                    "media_id": media_id,
                    "run_id": row.get("run_id") or row.get("job_id"),
                    "source_file_identity": row.get("source_file_identity"),
                    "source_hash": row.get("source_hash") or row.get("sha256"),
                    "artifact_path": f"items/{item_id}/{_FINAL_TIMELINE_FILE}",
                    "conversion_info_path": exported_conversion_path,
                }
            )

        if not items_manifest:
            raise ValueError("No completed item artifacts are available to download.")

        readme_lines = [
            "# TimelineForAudio Export",
            "",
            "This package was created by TimelineForAudio.",
            "",
            "TimelineForAudio converts source audio into timestamped speaker-separated transcript JSON for downstream tools.",
            "It does not infer real speaker names and does not summarize or rewrite the transcript.",
            "",
            "Each item directory contains:",
            "",
            "- `items/<item-id>/convert_info.json`: source, model, runtime, and processing-flow information.",
            f"- `items/<item-id>/{_FINAL_TIMELINE_FILE}`: speaker labels, timestamps, and transcript text.",
            "",
            "Generated at: `" + now_iso() + "`",
            "",
        ]
        write_text(staging_root / "README.md", "\n".join(readme_lines))
        created = shutil.make_archive(str(archive_base), "zip", root_dir=str(staging_root))
        return Path(created)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def generation_signature_for_settings(
    *,
    settings: dict[str, Any],
) -> str:
    diarization_enabled = True
    return build_conversion_signature(
        compute_mode=settings.get("computeMode"),
        diarization_enabled=diarization_enabled,
        vad_profile=_FIXED_VAD_PROFILE,
    )


def _refresh_queue_limit(settings: dict[str, Any], max_items: int | None) -> int | None:
    if max_items is not None:
        if max_items <= 0:
            raise ValueError("max_items must be greater than 0.")
        return int(max_items)
    return None


def create_refresh_run(
    *,
    settings: dict[str, Any] | None = None,
    source_ids: list[str] | None = None,
    output_root_id: str | None = None,
    reprocess_duplicates: bool = False,
    max_items: int | None = None,
) -> tuple[str | None, Path | None, dict[str, Any]]:
    settings = settings or load_settings()
    config = app_config_from_settings(settings)
    discovered = discover_audio(config)
    selected_source_ids = {value.lower() for value in source_ids or []}
    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = configured_path(str(output_root["path"]))
    ensure_dir(output_root_path)
    generation_signature = generation_signature_for_settings(
        settings=settings,
    )
    catalog = load_catalog(output_root_path)
    input_items: list[InputItem] = []
    skipped_rows: list[dict[str, Any]] = []
    deferred_rows: list[dict[str, Any]] = []
    queued_limit = _refresh_queue_limit(settings, max_items)

    for row in discovered.get("audio_files", []):
        source_name = str(row.get("source_name") or "")
        if selected_source_ids and source_name.lower() not in selected_source_ids:
            continue
        source_path = Path(str(row.get("path") or ""))
        if not source_path.exists() or not source_path.is_file():
            continue
        file_hash = sha256_file(source_path)
        source_root = _source_root_for_id(settings, source_name)
        source_root_path = (
            configured_path(str(source_root.get("path") or "")).resolve()
            if source_root is not None
            else None
        )
        relative_path = _relative_path_label(source_path, source_root_path)
        source_file_identity = _source_file_identity(source_name, relative_path)
        duplicate = catalog.get(catalog_key(file_hash, generation_signature, source_file_identity))
        if (
            duplicate
            and not reprocess_duplicates
            and _artifact_path_from_catalog_row(duplicate) is not None
        ):
            skipped_rows.append(
                {
                    "path": str(source_path),
                    "source_id": source_name,
                    "source_relative_path": relative_path,
                    "source_file_identity": source_file_identity,
                    "reason": "unchanged",
                    "source_hash": file_hash,
                    "duplicate_of": duplicate.get("audio_id") or duplicate.get("media_id"),
                    "run_id": duplicate.get("run_id"),
                }
            )
            continue
        if queued_limit is not None and len(input_items) >= queued_limit:
            deferred_rows.append(
                {
                    "path": str(source_path),
                    "source_id": source_name,
                    "source_relative_path": relative_path,
                    "source_file_identity": source_file_identity,
                    "reason": "batch_limit",
                    "source_hash": file_hash,
                }
            )
            continue
        input_items.append(
            InputItem(
                input_id=f"ref-{len(input_items) + 1:04d}",
                source_kind="configured_directory",
                source_id=source_name,
                original_path=str(source_path.resolve()),
                display_name=source_path.name,
                size_bytes=int(row.get("size_bytes") or source_path.stat().st_size),
                source_relative_path=relative_path,
                source_file_identity=source_file_identity,
            )
        )

    summary: dict[str, Any] = {
        "total_discovered": int(discovered.get("total_audio_files") or 0),
        "missing_sources": discovered.get("missing_sources", []),
        "selected_count": len(input_items) + len(skipped_rows) + len(deferred_rows),
        "queued_count": len(input_items),
        "skipped_count": len(skipped_rows),
        "deferred_count": len(deferred_rows),
        "queued_limit": queued_limit,
        "skipped": skipped_rows,
        "deferred": deferred_rows,
        "generation_signature": generation_signature,
        "artifact": "timeline",
    }
    if not input_items:
        return None, None, summary
    run_id, run_dir = create_run(
        settings=settings,
        input_items=input_items,
        output_root_id=output_root_id,
        reprocess_duplicates=reprocess_duplicates,
    )
    summary["run_id"] = run_id
    summary["run_dir"] = str(run_dir)
    return run_id, run_dir, summary


def _timeline_summary_from_artifact(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {
            "has_timeline": False,
            "turn_count": 0,
            "speaker_count": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {
            "has_timeline": True,
            "turn_count": 0,
            "speaker_count": 0,
        }
    turns = payload.get("turns", [])
    if not isinstance(turns, list):
        turns = []
    speakers = {
        str(turn.get("speaker") or "").strip()
        for turn in turns
        if isinstance(turn, dict) and str(turn.get("speaker") or "").strip()
    }
    turn_count = payload.get("turn_count")
    if not isinstance(turn_count, int):
        turn_count = len(turns)
    return {
        "has_timeline": True,
        "turn_count": turn_count,
        "speaker_count": len(speakers),
    }


def _probe_duration_sec(path: Path) -> float | None:
    try:
        from .ffmpeg_utils import probe_audio

        probed = probe_audio(path)
        value = probed.get("duration_seconds")
        return round(float(value), 3) if value else None
    except Exception:
        return None


def _catalog_rows_by_identity(catalog: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for row in catalog.values():
        identity = str(row.get("source_file_identity") or "").strip()
        if identity:
            rows.setdefault(identity, []).append(row)
    return rows


def _manifest_rows_by_identity(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for run in list_runs(settings):
        run_state = str(run.get("state") or "").lower()
        if run_state not in {"pending", "running", "failed"}:
            continue
        manifest_path = Path(str(run.get("run_dir") or "")) / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8-sig", errors="replace")
            )
        except (OSError, json.JSONDecodeError):
            continue
        for item in manifest.get("items", []):
            if not isinstance(item, dict):
                continue
            identity = str(item.get("source_file_identity") or "").strip()
            if not identity:
                continue
            rows[identity] = {
                **item,
                "run_id": run.get("run_id"),
                "run_dir": run.get("run_dir"),
                "run_state": run_state,
            }
    return rows


def _select_catalog_status(
    *,
    catalog_rows: list[dict[str, Any]],
    file_hash: str | None,
    generation_signature: str,
) -> tuple[str, dict[str, Any] | None]:
    if not catalog_rows:
        return "unprocessed", None

    available_rows = [
        row for row in catalog_rows if _artifact_path_from_catalog_row(row) is not None
    ]
    if not available_rows:
        return "unprocessed", None

    exact_rows = [
        row
        for row in available_rows
        if str(row.get("conversion_signature") or "") == generation_signature
        and (file_hash is None or str(row.get("source_hash") or "") == file_hash)
    ]
    if exact_rows:
        return "completed", exact_rows[0]

    if file_hash is not None:
        same_file_rows = [
            row
            for row in available_rows
            if str(row.get("source_hash") or "") == file_hash
        ]
        if same_file_rows:
            return "settings_changed", same_file_rows[0]

    return "changed", available_rows[0]


def list_audio_file_rows(
    *,
    settings: dict[str, Any] | None = None,
    include_probe: bool = False,
) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    config = app_config_from_settings(settings)
    discovered = discover_audio(config)
    output_root = _enabled_output_root(settings)
    output_root_path = configured_path(str(output_root["path"]))
    catalog_by_identity = _catalog_rows_by_identity(load_catalog(output_root_path))
    manifest_by_identity = _manifest_rows_by_identity(settings)
    generation_signature = generation_signature_for_settings(settings=settings)
    roots_by_id = {
        str(root.get("id") or "").lower(): root
        for root in _enabled_input_roots(settings)
    }
    rows: list[dict[str, Any]] = []

    for discovered_row in discovered.get("audio_files", []):
        source_id = str(discovered_row.get("source_name") or "")
        source_path = Path(str(discovered_row.get("path") or ""))
        if not source_path.exists() or not source_path.is_file():
            continue
        source_root = roots_by_id.get(source_id.lower())
        configured_root_path = (
            configured_path(str(source_root.get("path") or "")).resolve()
            if source_root is not None
            else None
        )
        original_root_path = (
            str(source_root.get("path") or "") if source_root is not None else ""
        )
        relative_path = _relative_path_label(source_path, configured_root_path)
        directory = str(Path(relative_path).parent).replace("\\", "/")
        if directory == ".":
            directory = ""
        source_file_identity = _source_file_identity(source_id, relative_path)
        catalog_candidates = catalog_by_identity.get(source_file_identity, [])
        file_hash = sha256_file(source_path) if catalog_candidates else None
        status, catalog_row = _select_catalog_status(
            catalog_rows=catalog_candidates,
            file_hash=file_hash,
            generation_signature=generation_signature,
        )
        manifest_row = manifest_by_identity.get(source_file_identity)
        if manifest_row is not None:
            manifest_status = str(manifest_row.get("status") or manifest_row.get("run_state") or "")
            run_state = str(manifest_row.get("run_state") or "")
            if run_state in {"pending", "running"}:
                status = "processing" if run_state == "running" else "queued"
                catalog_row = manifest_row
            elif manifest_status == "failed" and status == "unprocessed":
                status = "failed"
                catalog_row = manifest_row

        artifact_path = _artifact_path_from_catalog_row(catalog_row)
        media_id = (
            str(catalog_row.get("audio_id") or catalog_row.get("media_id") or "")
            if catalog_row
            else ""
        )
        run_id = str(catalog_row.get("run_id") or "") if catalog_row else ""
        duration_sec = None
        if catalog_row is not None:
            raw_duration = catalog_row.get("duration_seconds") or catalog_row.get("duration_sec")
            try:
                duration_sec = round(float(raw_duration), 3) if raw_duration else None
            except (TypeError, ValueError):
                duration_sec = None
        if duration_sec is None and include_probe:
            duration_sec = _probe_duration_sec(source_path)

        timeline_summary = _timeline_summary_from_artifact(artifact_path)
        media_dir = _media_dir_from_catalog_row(catalog_row) if catalog_row else None

        stat = source_path.stat()
        rows.append(
            {
                "source_id": source_id,
                "source_display_name": str(
                    source_id or "Audio"
                ),
                "root_path": original_root_path,
                "relative_path": relative_path,
                "directory": directory,
                "file_name": source_path.name,
                "display_path": _display_path_from_root(
                    original_root_path,
                    relative_path,
                    source_path,
                ),
                "container_path": str(source_path),
                "size_bytes": int(discovered_row.get("size_bytes") or stat.st_size),
                "modified_at": _iso_from_timestamp(stat.st_mtime),
                "duration_sec": duration_sec,
                "status": status,
                "run_id": run_id,
                "media_id": media_id,
                "has_timeline": bool(timeline_summary["has_timeline"]),
                "has_audio": False,
                "turn_count": int(timeline_summary["turn_count"]),
                "speaker_count": int(timeline_summary["speaker_count"]),
                "source_file_identity": source_file_identity,
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("modified_at") or ""),
            str(row.get("source_file_identity") or ""),
        ),
        reverse=True,
    )
    return rows


def list_audio_file_page(
    *,
    settings: dict[str, Any] | None = None,
    include_probe: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    rows = list_audio_file_rows(settings=settings, include_probe=include_probe)
    return list_payload(
        key="files",
        count_key="file_count",
        total_key="total_files",
        returned_key="returned_files",
        rows=rows,
        page=page,
        page_size=page_size,
        sort_fields=["modified_at", "source_file_identity"],
    )


def _iter_run_dirs(output_path: Path) -> list[Path]:
    rows = list(_runs_root(output_path).glob("run-*"))
    rows.extend(output_path.glob("run-*"))
    return sorted({item.resolve(): item for item in rows}.values(), key=lambda item: item.name, reverse=True)


def settings_snapshot(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    token = settings_token(settings) or None
    inputs = _enabled_input_roots(settings)
    output_roots = _enabled_output_root_list(settings)
    blocking_reasons: list[str] = []
    if not token:
        blocking_reasons.append("needs_token")
    if not inputs:
        blocking_reasons.append("needs_input")
    if not output_roots:
        blocking_reasons.append("needs_master")
    setup_state = "ready" if not blocking_reasons else blocking_reasons[0]
    token_payload: dict[str, Any] = {
        "configured": bool(token),
    }
    if token:
        token_payload["preview"] = token_preview(token)
    return {
        "setup": {
            "state": setup_state,
            "blocking_reasons": blocking_reasons,
        },
        "token": token_payload,
        "compute": {
            "mode": str(settings.get("computeMode") or "cpu"),
        },
        "runtime": settings.get("runtime", {}),
        "inputs": [str(root.get("path") or "") for root in inputs],
        "master": str(output_roots[0]["path"]) if output_roots else None,
    }


def token_preview(token: str | None) -> str:
    value = str(token or "").strip()
    bullet = "\u2022"
    if not value:
        return ""
    if len(value) <= 8:
        return bullet * len(value)
    return f"{value[:4]}{bullet * max(4, len(value) - 8)}{value[-4:]}"

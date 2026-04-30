from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from uuid import uuid4

from .catalog import catalog_key, load_catalog
from .contracts import InputItem, RunRequest, RunResult, RunStatus
from .discovery import discover_audio
from .fs_utils import ensure_dir, now_iso, slugify, write_text
from .hashing import sha256_file
from .vad_profile import resolve_vad_profile
from .signature import (
    ACOUSTIC_UNIT_BACKEND_NAME,
    DIARIZATION_MODEL_ID,
    PIPELINE_VERSION,
    VAD_BACKEND,
    VAD_MODEL_ID,
    build_conversion_signature,
    normalize_compute_mode,
    resolve_acoustic_unit_model_id,
)
from .settings import configured_path, load_huggingface_token, load_settings

_DATETIME_PATTERNS = [
    re.compile(
        r"(?P<year>20\d{2})[-_ ]?(?P<month>\d{2})[-_ ]?(?P<day>\d{2})[T _-]?(?P<hour>\d{2})[-_ ]?(?P<minute>\d{2})[-_ ]?(?P<second>\d{2})"
    ),
    re.compile(
        r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})[-_ ]?(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    ),
]
_FIXED_VAD_PROFILE = resolve_vad_profile(None)


def _allowed_extensions(settings: dict[str, Any]) -> set[str]:
    return {
        ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}"
        for ext in settings.get("audioExtensions", settings.get("videoExtensions", []))
        if str(ext).strip()
    }


def _enabled_output_root(
    settings: dict[str, Any], output_root_id: str | None = None
) -> dict[str, Any]:
    enabled = [
        root
        for root in settings.get("outputRoots", [])
        if root.get("enabled", True) and root.get("path")
    ]
    if output_root_id:
        for root in enabled:
            if str(root.get("id") or "").lower() == output_root_id.lower():
                return root
        raise ValueError(f"Output root not found or disabled: {output_root_id}")
    if not enabled:
        raise ValueError("No enabled output root is configured.")
    return enabled[0]


def _enabled_input_roots(settings: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        root
        for root in settings.get("inputRoots", [])
        if root.get("enabled", True) and root.get("path")
    ]


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
    return f"{source}:{relative}"


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
                name=str(root.get("id") or root.get("displayName") or "source"),
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
    return [
        root
        for root in settings.get("outputRoots", [])
        if root.get("enabled", True) and root.get("path")
    ]


def get_active_run(settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    for row in list_runs(settings):
        if str(row.get("state", "")).lower() in {"pending", "running"}:
            return row
    return None


def find_run_dir(run_id: str, settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    for root in _enabled_output_root_list(settings):
        candidate = configured_path(str(root["path"])) / run_id
        if candidate.exists():
            return candidate
    raise ValueError(f"Run not found: {run_id}")


def build_run_archive(
    run_id: str,
    *,
    settings: dict[str, Any] | None = None,
    output: Path | None = None,
    artifact_kind: str = "timeline",
) -> Path:
    run_dir = find_run_dir(run_id, settings)
    normalized_artifact_kind = _normalize_export_artifact_kind(artifact_kind)
    archive_stem = f"{run_id}-{normalized_artifact_kind}"
    archive_base = (output if output is not None else run_dir.parent / archive_stem).resolve()
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()

    staging_root = Path(
        tempfile.mkdtemp(prefix=f"{archive_stem}-export-", dir=str(archive_base.parent))
    )
    try:
        _build_export_package(run_dir, run_id, staging_root, normalized_artifact_kind)
        created = shutil.make_archive(str(archive_base), "zip", root_dir=str(staging_root))
        return Path(created)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _conversion_info_candidate_paths(run_dir: Path) -> list[Path]:
    return [
        run_dir / "CONVERSION_INFO.md",
        run_dir / "TRANSCRIPTION_INFO.md",
    ]


def _find_conversion_info_path(run_dir: Path) -> Path | None:
    for candidate in _conversion_info_candidate_paths(run_dir):
        if candidate.exists():
            return candidate
    return None


def _normalize_export_artifact_kind(value: str | None) -> str:
    normalized = str(value or "timeline").strip().lower()
    if normalized in {
        "timeline",
        "speaker-acoustic-units",
        "speaker_acoustic_units",
        "speaker-acoustic-units-timeline",
    }:
        return "timeline"
    raise ValueError(f"Unsupported artifact kind: {value}")


def _artifact_export_title(artifact_kind: str) -> str:
    return "Speaker Acoustic Units Timeline"


def _build_export_package(
    run_dir: Path,
    run_id: str,
    export_root: Path,
    artifact_kind: str,
) -> None:
    normalized_artifact_kind = _normalize_export_artifact_kind(artifact_kind)
    artifact_root = export_root / normalized_artifact_kind
    artifact_root.mkdir(parents=True, exist_ok=True)
    timelines: list[dict[str, str]] = []
    media_root = run_dir / "media"
    if media_root.exists():
        for media_dir in sorted(media_root.iterdir()):
            if not media_dir.is_dir():
                continue
            timeline_path = media_dir / "timeline" / "speaker-acoustic-units-timeline.json"
            if not timeline_path.exists():
                continue
            source_path = media_dir / "source" / "source-record.json"
            if not source_path.exists():
                source_path = media_dir / "source.json"
            source_info = (
                json.loads(source_path.read_text(encoding="utf-8-sig", errors="replace"))
                if source_path.exists()
                else {}
            )
            label = _best_export_label(media_dir.name, source_info)
            timelines.append(
                {
                    "media_id": media_dir.name,
                    "timeline_path": str(timeline_path),
                    "label": label,
                    "source_path": str(source_info.get("original_path") or ""),
                }
            )

    timelines.sort(key=lambda row: (row["label"], row["media_id"]))

    conversion_info_path = _find_conversion_info_path(run_dir)
    if conversion_info_path is not None:
        shutil.copy2(conversion_info_path, export_root / "CONVERSION_INFO.md")

    used_names: set[str] = set()
    exported_rows: list[dict[str, str]] = []
    for row in timelines:
        source_path = Path(row["timeline_path"])
        if not source_path.exists():
            continue
        timeline_file_name = _ensure_unique_export_file_name(f"{row['label']}.json", used_names)
        destination = artifact_root / timeline_file_name
        destination.write_text(
            source_path.read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        exported_row = {
            "label": row["label"],
            "source_path": row["source_path"],
            "artifact_path": f"{artifact_root.name}/{timeline_file_name}",
        }
        exported_rows.append(exported_row)

    if not exported_rows:
        title = _artifact_export_title(normalized_artifact_kind)
        raise ValueError(f"No completed {title} artifacts are available to download for this run.")

    _write_export_index_html(
        export_root=export_root,
        run_id=run_id,
        artifact_kind=normalized_artifact_kind,
        exported_rows=exported_rows,
        has_conversion_info=(export_root / "CONVERSION_INFO.md").exists(),
        has_failure_report=(export_root / "FAILURE_REPORT.md").exists(),
        has_worker_log=(export_root / "logs" / "worker.log").exists(),
    )


def _write_export_index_html(
    *,
    export_root: Path,
    run_id: str,
    artifact_kind: str,
    exported_rows: list[dict[str, str]],
    has_conversion_info: bool,
    has_failure_report: bool,
    has_worker_log: bool,
) -> None:
    def anchor(path: str, label: str) -> str:
        if not path:
            return '<span class="muted">N/A</span>'
        return f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>'

    top_links: list[str] = []
    if has_conversion_info:
        top_links.append('<li><a href="CONVERSION_INFO.md">CONVERSION_INFO.md</a></li>')
    if has_failure_report:
        top_links.append('<li><a href="FAILURE_REPORT.md">FAILURE_REPORT.md</a></li>')
    if has_worker_log:
        top_links.append('<li><a href="logs/worker.log">logs/worker.log</a></li>')

    item_rows = []
    for row in exported_rows:
        item_rows.append(
            "\n".join(
                [
                    "<tr>",
                    f"<td>{html.escape(row['label'])}</td>",
                    f"<td><code>{html.escape(row['source_path'] or '')}</code></td>",
                    f"<td>{anchor(row['artifact_path'], _artifact_export_title(artifact_kind).lower())}</td>",
                    "</tr>",
                ]
            )
        )

    document = "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>TimelineForAudio export {html.escape(run_id)}</title>",
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            "  <style>",
            "    :root { color-scheme: light; }",
            "    body { font-family: 'Segoe UI', sans-serif; margin: 24px; color: #1e293b; background: #f8fafc; }",
            "    h1, h2 { margin: 0 0 12px; }",
            "    p, li { line-height: 1.6; }",
            "    code { font-family: Consolas, monospace; font-size: 12px; }",
            "    .panel { background: white; border: 1px solid #dbe4ee; border-radius: 16px; padding: 20px; margin-bottom: 20px; }",
            "    table { width: 100%; border-collapse: collapse; background: white; }",
            "    th, td { border-bottom: 1px solid #e2e8f0; padding: 10px 12px; text-align: left; vertical-align: top; }",
            "    th { background: #eff6ff; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }",
            "    a { color: #0f766e; text-decoration: none; }",
            "    a:hover { text-decoration: underline; }",
            "    .muted { color: #94a3b8; }",
            "  </style>",
            "</head>",
            "<body>",
            '  <section class="panel">',
            "    <h1>TimelineForAudio export</h1>",
            f"    <p>Run ID: <code>{html.escape(run_id)}</code></p>",
            f"    <p>This package contains the {_artifact_export_title(artifact_kind)} export for the selected run.</p>",
            "  </section>",
            '  <section class="panel">',
            "    <h2>Top-level files</h2>",
            f"    <ul>{''.join(top_links)}</ul>",
            "  </section>",
            '  <section class="panel">',
            "    <h2>Per-item artifacts</h2>",
            "    <table>",
            "      <thead>",
            f"        <tr><th>Item</th><th>Source</th><th>{html.escape(_artifact_export_title(artifact_kind))}</th></tr>",
            "      </thead>",
            "      <tbody>",
            *item_rows,
            "      </tbody>",
            "    </table>",
            "  </section>",
            "</body>",
            "</html>",
            "",
        ]
    )
    (export_root / "README.html").write_text(document, encoding="utf-8")


def _best_export_label(media_id: str, source_info: dict[str, Any]) -> str:
    candidates = [
        str(source_info.get("recorded_at") or "").strip(),
        str(source_info.get("captured_at") or "").strip(),
        str(source_info.get("display_name") or "").strip(),
        str(source_info.get("original_path") or "").strip(),
        media_id,
    ]
    for candidate in candidates:
        parsed = _parse_best_effort_datetime(candidate)
        if parsed is not None:
            return parsed.strftime("%Y-%m-%d %H-%M-%S")

    fallback = Path(
        str(source_info.get("resolved_path") or source_info.get("original_path") or media_id)
    )
    if fallback.exists():
        last_write = fallback.stat().st_mtime
        if last_write > 0:
            return datetime.fromtimestamp(last_write).strftime("%Y-%m-%d %H-%M-%S")
        creation_time = fallback.stat().st_ctime
        if creation_time > 0:
            return datetime.fromtimestamp(creation_time).strftime("%Y-%m-%d %H-%M-%S")

    return slugify(media_id)


def _ensure_unique_export_file_name(file_name: str, used_names: set[str]) -> str:
    path = Path(file_name)
    candidate = path.name
    suffix = 2
    while candidate.lower() in used_names:
        candidate = f"{path.stem}-{suffix}{path.suffix}"
        suffix += 1
    used_names.add(candidate.lower())
    return candidate


def _parse_best_effort_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for pattern in _DATETIME_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        parts = {key: int(text) for key, text in match.groupdict().items()}
        try:
            return datetime(
                parts["year"],
                parts["month"],
                parts["day"],
                parts["hour"],
                parts["minute"],
                parts["second"],
            )
        except ValueError:
            return None
    return None


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

    run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    run_dir = output_root_path / run_id
    ensure_dir(run_dir / "media")
    ensure_dir(run_dir / "llm")
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
        acoustic_unit_backend=ACOUSTIC_UNIT_BACKEND_NAME,
        acoustic_unit_model_id=resolve_acoustic_unit_model_id(),
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
    conversion_info = "# Conversion Info\n\nPending worker pickup.\n"
    write_text(run_dir / "CONVERSION_INFO.md", conversion_info)
    write_text(run_dir / "NOTICE.md", "# Notice\n\nPending worker pickup.\n")

    return run_id, run_dir


def _artifact_path_from_catalog_row(row: dict[str, Any] | None) -> Path | None:
    if not row:
        return None
    run_dir = row.get("run_dir")
    media_id = row.get("audio_id") or row.get("media_id")
    if not run_dir or not media_id:
        return None
    media_dir = Path(str(run_dir)) / "media" / str(media_id)
    for candidate in (
        media_dir / "timeline" / "speaker-acoustic-units-timeline.json",
    ):
        if candidate.exists():
            return candidate
    return None


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
        "artifact": "speaker-acoustic-units-timeline",
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
            elif manifest_status == "failed":
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
        media_dir = (
            Path(str(catalog_row.get("run_dir") or "")) / "media" / media_id
            if catalog_row and media_id
            else None
        )

        stat = source_path.stat()
        rows.append(
            {
                "source_id": source_id,
                "source_display_name": str(
                    (source_root or {}).get("displayName") or source_id or "Audio"
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
                "has_audio": bool(
                    media_dir is not None
                    and (media_dir / "source" / "audio-normalized.wav").exists()
                ),
                "turn_count": int(timeline_summary["turn_count"]),
                "speaker_count": int(timeline_summary["speaker_count"]),
                "source_file_identity": source_file_identity,
            }
        )

    rows.sort(
        key=lambda row: (
            str(row.get("source_display_name") or "").lower(),
            str(row.get("directory") or "").lower(),
            str(row.get("file_name") or "").lower(),
        )
    )
    return rows


def _iter_run_dirs(output_path: Path) -> list[Path]:
    rows = list(output_path.glob("run-*"))
    return sorted({item.resolve(): item for item in rows}.values(), key=lambda item: item.name, reverse=True)


def settings_snapshot(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    token = load_huggingface_token()
    return {
        "has_token": bool(token),
        "token_preview": token_preview(token),
        "ready": bool(token),
        "diarization_required": True,
        "compute_mode": str(settings.get("computeMode") or "cpu"),
        "input_roots": _enabled_input_roots(settings),
        "output_roots": _enabled_output_root_list(settings),
    }


def token_preview(token: str | None) -> str:
    value = str(token or "").strip()
    bullet = "\u2022"
    if not value:
        return ""
    if len(value) <= 8:
        return bullet * len(value)
    return f"{value[:4]}{bullet * max(4, len(value) - 8)}{value[-4:]}"

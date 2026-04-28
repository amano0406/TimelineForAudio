from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import InputItem, JobRequest, JobResult, JobStatus
from .context_builder import CONTEXT_BUILDER_VERSION
from .discovery import discover_audio
from .fs_utils import ensure_dir, now_iso, slugify, write_text
from .reconstruction import (
    resolve_reconstruction_backend,
    resolve_reconstruction_model_id,
    resolve_reconstruction_prompt_version,
)
from .signature import (
    CONTEXT_BUILDER_VERSION as SIGNATURE_CONTEXT_BUILDER_VERSION,
    DIARIZATION_MODEL_ID,
    PIPELINE_VERSION,
    TRANSCRIPTION_BACKEND,
    VAD_BACKEND,
    VAD_MODEL_ID,
    build_conversion_signature,
    normalize_compute_mode,
    resolve_transcription_model_id,
)
from .settings import load_huggingface_token, load_settings

_DATETIME_PATTERNS = [
    re.compile(
        r"(?P<year>20\d{2})[-_ ]?(?P<month>\d{2})[-_ ]?(?P<day>\d{2})[T _-]?(?P<hour>\d{2})[-_ ]?(?P<minute>\d{2})[-_ ]?(?P<second>\d{2})"
    ),
    re.compile(
        r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})[-_ ]?(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})"
    ),
]


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

    def add_path(path: Path, source_kind: str, source_id: str) -> None:
        resolved = path.resolve()
        key = str(resolved).lower()
        if key in seen_paths:
            return
        if not resolved.exists() or not resolved.is_file():
            raise ValueError(f"Input file was not found: {resolved}")
        if resolved.suffix.lower() not in allowed_extensions:
            return
        seen_paths.add(key)
        size_bytes = resolved.stat().st_size
        rows.append(
            InputItem(
                input_id=f"{source_kind[:4]}-{len(rows) + 1:04d}",
                source_kind=source_kind,
                source_id=source_id,
                original_path=str(resolved),
                display_name=resolved.name,
                size_bytes=size_bytes,
            )
        )

    for file_path in files or []:
        add_path(file_path, "local_file", "local")

    for directory in directories or []:
        resolved_directory = directory.resolve()
        if not resolved_directory.exists() or not resolved_directory.is_dir():
            raise ValueError(f"Input directory was not found: {resolved_directory}")
        for file_path in _iter_audio_files(resolved_directory, allowed_extensions):
            add_path(file_path, "local_directory", str(resolved_directory))

    if source_ids:
        from .cli import _runtime_config  # local import to avoid circular top-level import

        selected_ids = {value.lower() for value in source_ids}
        config = _runtime_config()
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
            add_path(
                Path(str(row["path"])), "mounted_root", str(source_root.get("id") or source_name)
            )

    return rows


def list_runs(settings: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    settings = settings or load_settings()
    rows: list[dict[str, Any]] = []
    for root in _enabled_output_root_list(settings):
        output_path = Path(str(root["path"]))
        if not output_path.exists():
            continue
        for run_dir in _iter_job_dirs(output_path):
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
                    "job_id": request.get("job_id", run_dir.name),
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


def find_run_dir(job_id: str, settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_settings()
    for root in _enabled_output_root_list(settings):
        candidate = Path(str(root["path"])) / job_id
        if candidate.exists():
            return candidate
    raise ValueError(f"Job not found: {job_id}")


def build_run_archive(
    job_id: str,
    *,
    settings: dict[str, Any] | None = None,
    output: Path | None = None,
    artifact_kind: str = "readable-text",
) -> Path:
    run_dir = find_run_dir(job_id, settings)
    normalized_artifact_kind = _normalize_export_artifact_kind(artifact_kind)
    archive_stem = f"{job_id}-{normalized_artifact_kind}"
    archive_base = (output if output is not None else run_dir.parent / archive_stem).resolve()
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()

    staging_root = Path(
        tempfile.mkdtemp(prefix=f"{archive_stem}-export-", dir=str(archive_base.parent))
    )
    try:
        _build_export_package(run_dir, job_id, staging_root, normalized_artifact_kind)
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
    normalized = str(value or "readable-text").strip().lower()
    if normalized in {"readable-text", "readable_text", "readable"}:
        return "readable-text"
    if normalized == "ipa":
        return "ipa"
    raise ValueError(f"Unsupported artifact kind: {value}")


def _artifact_export_title(artifact_kind: str) -> str:
    return "Readable Text" if artifact_kind == "readable-text" else "IPA"


def _build_export_package(
    run_dir: Path,
    job_id: str,
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
            readable_text_path = media_dir / "readable-text" / "Readable Text.md"
            ipa_path = media_dir / "ipa" / "IPA.md"
            if not readable_text_path.exists() and not ipa_path.exists():
                continue
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
                    "readable_text_path": str(readable_text_path),
                    "ipa_path": str(ipa_path),
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
        source_key = "readable_text_path" if normalized_artifact_kind == "readable-text" else "ipa_path"
        source_path = Path(row[source_key])
        if not source_path.exists():
            continue
        timeline_file_name = _ensure_unique_export_file_name(f"{row['label']}.md", used_names)
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
        raise ValueError(f"No completed {title} artifacts are available to download for this job.")

    _write_export_index_html(
        export_root=export_root,
        job_id=job_id,
        artifact_kind=normalized_artifact_kind,
        exported_rows=exported_rows,
        has_conversion_info=(export_root / "CONVERSION_INFO.md").exists(),
        has_failure_report=(export_root / "FAILURE_REPORT.md").exists(),
        has_worker_log=(export_root / "logs" / "worker.log").exists(),
    )


def _write_export_index_html(
    *,
    export_root: Path,
    job_id: str,
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
            f"  <title>TimelineForAudio export {html.escape(job_id)}</title>",
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
            f"    <p>Job ID: <code>{html.escape(job_id)}</code></p>",
            f"    <p>This package contains the {_artifact_export_title(artifact_kind)} export for the selected job.</p>",
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


def create_job(
    *,
    settings: dict[str, Any] | None = None,
    input_items: list[InputItem],
    output_root_id: str | None = None,
    reprocess_duplicates: bool = False,
    readable_text_enabled: bool = True,
    supplemental_context_text: str | None = None,
) -> tuple[str, Path]:
    settings = settings or load_settings()
    if not input_items:
        raise ValueError("No input audio files were selected.")

    output_root = _enabled_output_root(settings, output_root_id)
    output_root_path = Path(str(output_root["path"]))
    ensure_dir(output_root_path)

    job_id = f"job-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    run_dir = output_root_path / job_id
    ensure_dir(run_dir / "media")
    ensure_dir(run_dir / "llm")
    ensure_dir(run_dir / "logs")

    diarization_enabled = bool(load_huggingface_token()) and bool(
        settings.get("huggingfaceTermsConfirmed", False)
    )
    language_hint = str(settings.get("uiLanguage") or "en").strip() or "en"
    supplemental_context_text = (
        supplemental_context_text.strip()
        if supplemental_context_text and supplemental_context_text.strip()
        else None
    )
    compute_mode = normalize_compute_mode(settings.get("computeMode"))
    request = JobRequest(
        schema_version=1,
        job_id=job_id,
        created_at=now_iso(),
        output_root_id=str(output_root.get("id") or "runs"),
        output_root_path=str(output_root_path),
        profile="quality-first",
        compute_mode=compute_mode,
        pipeline_version=PIPELINE_VERSION,
        conversion_signature=build_conversion_signature(
            compute_mode=settings.get("computeMode"),
            diarization_enabled=diarization_enabled,
            language_hint=language_hint,
            supplemental_context_text=supplemental_context_text,
            context_builder_version=SIGNATURE_CONTEXT_BUILDER_VERSION,
            readable_text_enabled=readable_text_enabled,
        ),
        transcription_backend=TRANSCRIPTION_BACKEND,
        transcription_model_id=resolve_transcription_model_id(),
        supplemental_context_text=supplemental_context_text,
        context_builder_version=CONTEXT_BUILDER_VERSION,
        diarization_enabled=diarization_enabled,
        diarization_model_id=DIARIZATION_MODEL_ID if diarization_enabled else None,
        vad_backend=VAD_BACKEND,
        vad_model_id=VAD_MODEL_ID,
        reprocess_duplicates=reprocess_duplicates,
        token_enabled=bool(load_huggingface_token()),
        input_items=input_items,
        language_hint=language_hint,
        readable_text_enabled=readable_text_enabled,
        reconstruction_backend=resolve_reconstruction_backend(language_hint, compute_mode)
        if readable_text_enabled
        else None,
        reconstruction_model_id=resolve_reconstruction_model_id(language_hint, compute_mode)
        if readable_text_enabled
        else None,
        reconstruction_prompt_version=resolve_reconstruction_prompt_version(language_hint, compute_mode)
        if readable_text_enabled
        else None,
    )
    status = JobStatus(
        job_id=job_id,
        state="pending",
        current_stage="queued",
        message="Queued for worker pickup.",
        items_total=len(input_items),
        updated_at=now_iso(),
    )
    result = JobResult(
        job_id=job_id,
        state="pending",
        run_dir=str(run_dir),
        output_root_id=str(output_root.get("id") or "runs"),
        output_root_path=str(output_root_path),
    )
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
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

    return job_id, run_dir


def _iter_job_dirs(output_path: Path) -> list[Path]:
    rows = list(output_path.glob("job-*"))
    rows.extend(output_path.glob("run-*"))
    return sorted({item.resolve(): item for item in rows}.values(), key=lambda item: item.name, reverse=True)


def settings_snapshot(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    token = load_huggingface_token()
    return {
        "has_token": bool(token),
        "terms_confirmed": bool(settings.get("huggingfaceTermsConfirmed", False)),
        "ready": bool(token) and bool(settings.get("huggingfaceTermsConfirmed", False)),
        "compute_mode": str(settings.get("computeMode") or "cpu"),
        "context_builder_version": str(
            settings.get("contextBuilderVersion") or CONTEXT_BUILDER_VERSION
        ),
        "input_roots": _enabled_input_roots(settings),
        "output_roots": _enabled_output_root_list(settings),
    }

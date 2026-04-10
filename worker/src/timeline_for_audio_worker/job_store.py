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
from .signature import (
    CONTEXT_BUILDER_VERSION as SIGNATURE_CONTEXT_BUILDER_VERSION,
    DIARIZATION_MODEL_ID,
    PIPELINE_VERSION,
    TRANSCRIPTION_BACKEND,
    VAD_BACKEND,
    VAD_MODEL_ID,
    build_conversion_signature,
    normalize_compute_mode,
    normalize_processing_quality,
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
) -> Path:
    run_dir = find_run_dir(job_id, settings)
    archive_base = (output if output is not None else run_dir.parent / job_id).resolve()
    archive_base.parent.mkdir(parents=True, exist_ok=True)
    archive_path = archive_base.with_suffix(".zip")
    if archive_path.exists():
        archive_path.unlink()

    staging_root = Path(tempfile.mkdtemp(prefix=f"{job_id}-export-", dir=str(archive_base.parent)))
    try:
        _build_export_package(run_dir, job_id, staging_root)
        created = shutil.make_archive(str(archive_base), "zip", root_dir=str(staging_root))
        return Path(created)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)


def _build_export_package(run_dir: Path, job_id: str, export_root: Path) -> None:
    timelines_root = export_root / "timelines"
    pass1_transcripts_root = export_root / "pass1-transcripts"
    pass2_transcripts_root = export_root / "pass2-transcripts"
    context_docs_root = export_root / "context-docs"
    speaker_summaries_root = export_root / "speaker-summaries"
    feature_summaries_root = export_root / "audio-feature-summaries"
    timelines_root.mkdir(parents=True, exist_ok=True)
    pass1_transcripts_root.mkdir(parents=True, exist_ok=True)
    pass2_transcripts_root.mkdir(parents=True, exist_ok=True)
    context_docs_root.mkdir(parents=True, exist_ok=True)
    speaker_summaries_root.mkdir(parents=True, exist_ok=True)
    feature_summaries_root.mkdir(parents=True, exist_ok=True)
    timelines: list[dict[str, str]] = []
    media_root = run_dir / "media"
    if media_root.exists():
        for media_dir in sorted(media_root.iterdir()):
            if not media_dir.is_dir():
                continue
            timeline_path = media_dir / "timeline" / "timeline.md"
            if not timeline_path.exists():
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
                    "timeline_path": str(timeline_path),
                    "label": label,
                    "source_path": str(source_info.get("original_path") or ""),
                    "pass1_transcript_path": str(media_dir / "transcript" / "pass1.md"),
                    "pass2_transcript_path": str(media_dir / "transcript" / "pass2.md"),
                    "context_doc_path": str(media_dir / "transcript" / "context_merged.txt"),
                    "speaker_summary_path": str(media_dir / "analysis" / "speaker_summary.md"),
                    "audio_feature_summary_path": str(
                        media_dir / "analysis" / "audio_features.md"
                    ),
                }
            )

    timelines.sort(key=lambda row: (row["label"], row["media_id"]))

    transcription_info_path = run_dir / "TRANSCRIPTION_INFO.md"
    if transcription_info_path.exists():
        shutil.copy2(transcription_info_path, export_root / "TRANSCRIPTION_INFO.md")

    used_names: set[str] = set()
    exported_rows: list[dict[str, str]] = []
    for row in timelines:
        timeline_file_name = _ensure_unique_export_file_name(f"{row['label']}.md", used_names)
        destination = timelines_root / timeline_file_name
        destination.write_text(
            Path(row["timeline_path"]).read_text(encoding="utf-8", errors="replace"),
            encoding="utf-8",
        )
        exported_row = {
            "label": row["label"],
            "source_path": row["source_path"],
            "timeline_path": f"timelines/{timeline_file_name}",
            "pass1_transcript_path": "",
            "pass2_transcript_path": "",
            "context_doc_path": "",
            "speaker_summary_path": "",
            "audio_feature_summary_path": "",
        }
        export_specs = (
            ("pass1_transcript_path", pass1_transcripts_root, ".md"),
            ("pass2_transcript_path", pass2_transcripts_root, ".md"),
            ("context_doc_path", context_docs_root, ".txt"),
            ("speaker_summary_path", speaker_summaries_root, ".md"),
            ("audio_feature_summary_path", feature_summaries_root, ".md"),
        )
        for source_key, target_root, extension in export_specs:
            source_path = Path(row[source_key])
            if source_path.exists():
                target_name = f"{Path(timeline_file_name).stem}{extension}"
                target_root.joinpath(target_name).write_text(
                    source_path.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
                exported_row[source_key] = f"{target_root.name}/{target_name}"
        exported_rows.append(exported_row)

    _write_export_index_html(
        export_root=export_root,
        job_id=job_id,
        exported_rows=exported_rows,
        has_transcription_info=(export_root / "TRANSCRIPTION_INFO.md").exists(),
        has_failure_report=(export_root / "FAILURE_REPORT.md").exists(),
        has_worker_log=(export_root / "logs" / "worker.log").exists(),
    )


def _write_export_index_html(
    *,
    export_root: Path,
    job_id: str,
    exported_rows: list[dict[str, str]],
    has_transcription_info: bool,
    has_failure_report: bool,
    has_worker_log: bool,
) -> None:
    def anchor(path: str, label: str) -> str:
        if not path:
            return '<span class="muted">N/A</span>'
        return f'<a href="{html.escape(path, quote=True)}">{html.escape(label)}</a>'

    top_links: list[str] = []
    if has_transcription_info:
        top_links.append('<li><a href="TRANSCRIPTION_INFO.md">TRANSCRIPTION_INFO.md</a></li>')
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
                    f"<td>{anchor(row['timeline_path'], 'timeline')}</td>",
                    f"<td>{anchor(row['pass1_transcript_path'], 'pass1')}</td>",
                    f"<td>{anchor(row['pass2_transcript_path'], 'pass2')}</td>",
                    f"<td>{anchor(row['context_doc_path'], 'context')}</td>",
                    f"<td>{anchor(row['speaker_summary_path'], 'speaker')}</td>",
                    f"<td>{anchor(row['audio_feature_summary_path'], 'features')}</td>",
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
            "    <p>Open the links below to inspect the generated markdown, transcript artifacts, and summaries.</p>",
            "  </section>",
            '  <section class="panel">',
            "    <h2>Top-level files</h2>",
            f"    <ul>{''.join(top_links)}</ul>",
            "  </section>",
            '  <section class="panel">',
            "    <h2>Per-item artifacts</h2>",
            "    <table>",
            "      <thead>",
            "        <tr><th>Item</th><th>Source</th><th>Timeline</th><th>Pass1</th><th>Pass2</th><th>Context</th><th>Speaker</th><th>Features</th></tr>",
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
        return datetime.fromtimestamp(fallback.stat().st_mtime).strftime("%Y-%m-%d %H-%M-%S")

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
    request = JobRequest(
        schema_version=1,
        job_id=job_id,
        created_at=now_iso(),
        output_root_id=str(output_root.get("id") or "runs"),
        output_root_path=str(output_root_path),
        profile="quality-first",
        compute_mode=normalize_compute_mode(settings.get("computeMode")),
        processing_quality=normalize_processing_quality(settings.get("processingQuality")),
        pipeline_version=PIPELINE_VERSION,
        conversion_signature=build_conversion_signature(
            compute_mode=settings.get("computeMode"),
            processing_quality=settings.get("processingQuality"),
            diarization_enabled=diarization_enabled,
            supplemental_context_text=None,
            second_pass_enabled=True,
            context_builder_version=SIGNATURE_CONTEXT_BUILDER_VERSION,
        ),
        transcription_backend=TRANSCRIPTION_BACKEND,
        transcription_model_id=resolve_transcription_model_id(settings.get("processingQuality")),
        supplemental_context_text=None,
        second_pass_enabled=True,
        context_builder_version=CONTEXT_BUILDER_VERSION,
        diarization_enabled=diarization_enabled,
        diarization_model_id=DIARIZATION_MODEL_ID if diarization_enabled else None,
        vad_backend=VAD_BACKEND,
        vad_model_id=VAD_MODEL_ID,
        reprocess_duplicates=reprocess_duplicates,
        token_enabled=bool(load_huggingface_token()),
        input_items=input_items,
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
    write_text(
        run_dir / "TRANSCRIPTION_INFO.md", "# Transcription Info\n\nPending worker pickup.\n"
    )
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
        "processing_quality": str(settings.get("processingQuality") or "standard"),
        "second_pass_enabled": bool(settings.get("secondPassEnabled", True)),
        "context_builder_version": str(
            settings.get("contextBuilderVersion") or CONTEXT_BUILDER_VERSION
        ),
        "input_roots": _enabled_input_roots(settings),
        "output_roots": _enabled_output_root_list(settings),
    }

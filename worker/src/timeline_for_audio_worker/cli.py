from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from .config import AppConfig, load_config
from .discovery import discover_audio
from .fs_utils import now_iso
from .ipa_backend import resolve_ipa_backend
from .runtime_guard import assert_cli_runtime_allowed
from .vad_profile import resolve_vad_profile
from .job_store import (
    build_run_archive,
    app_config_from_settings,
    collect_input_items,
    create_job,
    create_refresh_job,
    find_run_dir,
    list_runs,
    settings_snapshot,
)
from .settings import (
    init_settings,
    load_huggingface_token,
    load_settings,
    save_huggingface_token,
    save_settings,
    save_worker_capabilities,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TimelineForAudio worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    settings_parser = subparsers.add_parser("settings", help="Show or update local settings.")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_init = settings_subparsers.add_parser(
        "init", help="Create settings.json from settings.example.json if it does not exist."
    )
    settings_init.add_argument("--json", action="store_true")
    settings_status = settings_subparsers.add_parser(
        "status", help="Show current settings readiness."
    )
    settings_status.add_argument("--json", action="store_true")
    settings_save = settings_subparsers.add_parser(
        "save", help="Save Hugging Face token and terms confirmation."
    )
    settings_save.add_argument("--token", type=str, required=False)
    settings_save.add_argument("--terms-confirmed", action="store_const", const=True, default=None)
    settings_save.add_argument("--compute-mode", choices=["cpu", "gpu"], required=False)
    settings_save.add_argument("--language", type=str, required=False)
    settings_save.add_argument("--ipa-backend", choices=["sudachi", "pyopenjtalk"], required=False)
    settings_save.add_argument("--vad-profile", choices=["default", "loose", "strict"], required=False)
    settings_save.add_argument("--json", action="store_true")
    input_root = settings_subparsers.add_parser(
        "input-root", help="Manage configured input directories."
    )
    input_root_subparsers = input_root.add_subparsers(dest="input_root_command", required=True)
    input_root_list = input_root_subparsers.add_parser("list", help="List input directories.")
    input_root_list.add_argument("--json", action="store_true")
    input_root_add = input_root_subparsers.add_parser("add", help="Add or update an input directory.")
    input_root_add.add_argument("--id", required=True)
    input_root_add.add_argument("--path", type=Path, required=True)
    input_root_add.add_argument("--display-name", required=False)
    input_root_add.add_argument("--disabled", action="store_true")
    input_root_add.add_argument("--json", action="store_true")
    input_root_remove = input_root_subparsers.add_parser("remove", help="Remove an input directory.")
    input_root_remove.add_argument("--id", required=True)
    input_root_remove.add_argument("--json", action="store_true")
    input_root_clear = input_root_subparsers.add_parser("clear", help="Remove all input directories.")
    input_root_clear.add_argument("--json", action="store_true")
    output_root = settings_subparsers.add_parser(
        "output-root", help="Manage the configured output directory."
    )
    output_root_subparsers = output_root.add_subparsers(dest="output_root_command", required=True)
    output_root_list = output_root_subparsers.add_parser("list", help="List output directories.")
    output_root_list.add_argument("--json", action="store_true")
    output_root_set = output_root_subparsers.add_parser("set", help="Set the primary output directory.")
    output_root_set.add_argument("--id", default="runs")
    output_root_set.add_argument("--path", type=Path, required=True)
    output_root_set.add_argument("--display-name", required=False)
    output_root_set.add_argument("--json", action="store_true")

    jobs_parser = subparsers.add_parser("jobs", help="Create or inspect jobs.")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command", required=True)
    jobs_list = jobs_subparsers.add_parser("list", help="List runs in the configured output root.")
    jobs_list.add_argument("--json", action="store_true")
    jobs_show = jobs_subparsers.add_parser("show", help="Show one run request/status/result.")
    jobs_show.add_argument("--job-id", type=str, required=True)
    jobs_show.add_argument("--json", action="store_true")
    jobs_create = jobs_subparsers.add_parser(
        "create", help="Create a job from files, directories, or configured source roots."
    )
    jobs_create.add_argument("--file", dest="files", action="append", type=Path, default=[])
    jobs_create.add_argument(
        "--directory", dest="directories", action="append", type=Path, default=[]
    )
    jobs_create.add_argument("--source-id", dest="source_ids", action="append", default=[])
    jobs_create.add_argument("--output-root-id", type=str, default="runs")
    jobs_create.add_argument("--language", type=str, required=False)
    jobs_create.add_argument("--ipa-backend", choices=["sudachi", "pyopenjtalk"], required=False)
    jobs_create.add_argument("--vad-profile", choices=["default", "loose", "strict"], required=False)
    jobs_create.add_argument("--supplemental-context", type=str, required=False)
    jobs_create.add_argument("--supplemental-context-file", type=Path, required=False)
    jobs_create.add_argument("--ipa-only", action="store_true")
    jobs_create.add_argument("--reprocess-duplicates", action="store_true")
    jobs_create.add_argument("--queue-only", action="store_true")
    jobs_create.add_argument("--json", action="store_true")
    jobs_run = jobs_subparsers.add_parser("run", help="Run one existing queued job.")
    jobs_run.add_argument("--job-id", type=str, required=True)
    jobs_run.add_argument("--json", action="store_true")
    jobs_archive = jobs_subparsers.add_parser(
        "archive", help="Create a ZIP archive for one completed job."
    )
    jobs_archive.add_argument("--job-id", type=str, required=True)
    jobs_archive.add_argument("--output", type=Path, required=False)
    jobs_archive.add_argument("--artifact-kind", choices=["readable-text", "ipa"], default="readable-text")
    jobs_archive.add_argument("--json", action="store_true")

    scan_parser = subparsers.add_parser(
        "scan", help="Scan configured source directories for audio files."
    )
    scan_parser.add_argument("--config", type=Path, required=False)
    scan_parser.add_argument("--output", type=Path, required=False)

    refresh_parser = subparsers.add_parser(
        "refresh", help="Read configured input directories and process changed audio only."
    )
    refresh_parser.add_argument("--source-id", dest="source_ids", action="append", default=[])
    refresh_parser.add_argument("--output-root-id", type=str, default="runs")
    refresh_parser.add_argument("--language", type=str, required=False)
    refresh_parser.add_argument("--ipa-backend", choices=["sudachi", "pyopenjtalk"], required=False)
    refresh_parser.add_argument("--vad-profile", choices=["default", "loose", "strict"], required=False)
    refresh_parser.add_argument("--supplemental-context", type=str, required=False)
    refresh_parser.add_argument("--supplemental-context-file", type=Path, required=False)
    refresh_parser.add_argument("--ipa-only", action="store_true")
    refresh_parser.add_argument("--reprocess-duplicates", action="store_true")
    refresh_parser.add_argument("--queue-only", action="store_true")
    refresh_parser.add_argument("--json", action="store_true")

    evaluate_parser = subparsers.add_parser(
        "evaluate", help="Compare produced turn artifact JSON with a reference JSON."
    )
    evaluate_parser.add_argument("--prediction", type=Path, required=False)
    evaluate_parser.add_argument("--job-id", type=str, required=False)
    evaluate_parser.add_argument("--media-id", type=str, required=False)
    evaluate_parser.add_argument(
        "--artifact-kind",
        choices=["ipa", "readable-text", "turns-source", "diarization"],
        default="ipa",
    )
    evaluate_parser.add_argument("--reference", type=Path, required=True)
    evaluate_parser.add_argument("--output-dir", type=Path, required=False)
    evaluate_parser.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("run-job", help="Run one specific job directory.")
    run_parser.add_argument("--job-dir", type=Path, required=True)

    daemon_parser = subparsers.add_parser(
        "daemon", help="Poll output roots and process pending jobs."
    )
    daemon_parser.add_argument("--poll-interval", type=int, default=5)

    return parser.parse_args()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _runtime_config() -> AppConfig:
    return app_config_from_settings(load_settings())


def _load_app_config(config_path: Path | None) -> AppConfig:
    if config_path:
        return load_config(config_path)
    return _runtime_config()


def cmd_scan(config_path: Path | None, output: Path | None) -> int:
    payload = discover_audio(_load_app_config(config_path))
    if output:
        write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_run_job(job_dir: Path) -> int:
    from .processor import process_job

    process_job(job_dir)
    return 0


def cmd_daemon(poll_interval: int) -> int:
    from .processor import process_job

    _write_worker_capabilities()
    while True:
        found = process_job()
        if not found:
            time.sleep(max(1, poll_interval))
    return 0


def _write_worker_capabilities() -> None:
    payload: dict[str, object] = {
        "generatedAt": now_iso(),
        "workerFlavor": os.getenv("TIMELINE_FOR_AUDIO_WORKER_FLAVOR", "cpu"),
        "torchInstalled": False,
        "torchCudaBuilt": False,
        "gpuAvailable": False,
        "deviceCount": 0,
        "deviceNames": [],
        "message": "Worker capability report created.",
    }
    try:
        import torch

        payload["torchInstalled"] = True
        payload["torchCudaBuilt"] = bool(torch.backends.cuda.is_built())
        payload["gpuAvailable"] = bool(torch.cuda.is_available())
        payload["deviceCount"] = int(torch.cuda.device_count()) if torch.cuda.is_available() else 0
        payload["deviceNames"] = (
            [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]
            if torch.cuda.is_available()
            else []
        )
        payload["deviceMemoryGiB"] = (
            [
                round(
                    torch.cuda.get_device_properties(index).total_memory / 1024 / 1024 / 1024,
                    1,
                )
                for index in range(torch.cuda.device_count())
            ]
            if torch.cuda.is_available()
            else []
        )
        payload["maxGpuMemoryGiB"] = max(payload["deviceMemoryGiB"], default=0.0)
        payload["message"] = (
            "GPU is available to the worker."
            if payload["gpuAvailable"]
            else "GPU is not available to the worker."
        )
    except Exception as exc:
        payload["message"] = f"Capability check failed: {exc}"

    save_worker_capabilities(payload)


def _print_payload(payload: dict[str, object] | list[dict[str, object]], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if isinstance(payload, list):
        if not payload:
            print("No jobs found.")
            return
        for row in payload:
            print(
                f"{row.get('job_id')} | {row.get('state')} | "
                f"{row.get('items_done', 0)}/{row.get('items_total', 0)} | "
                f"{row.get('current_stage', '')} | {row.get('run_dir', '')}"
            )
        return

    for key, value in payload.items():
        print(f"{key}: {value}")


def cmd_settings_status(as_json: bool) -> int:
    _print_payload(settings_snapshot(), as_json)
    return 0


def cmd_settings_save(
    token: str | None,
    terms_confirmed: bool | None,
    compute_mode: str | None,
    language: str | None,
    ipa_backend: str | None,
    vad_profile: str | None,
    as_json: bool,
) -> int:
    settings = load_settings()
    if token is not None:
        save_huggingface_token(token)
    if compute_mode is not None:
        settings["computeMode"] = compute_mode
    if language is not None:
        settings["uiLanguage"] = language
    if ipa_backend is not None:
        settings["ipaBackend"] = resolve_ipa_backend(ipa_backend)
    if vad_profile is not None:
        settings["vadProfile"] = resolve_vad_profile(vad_profile)
    if terms_confirmed is not None:
        settings["huggingfaceTermsConfirmed"] = terms_confirmed
    save_settings(settings)
    _print_payload(settings_snapshot(settings), as_json)
    return 0


def _root_list_payload(settings: dict[str, object], key: str) -> list[dict[str, object]]:
    value = settings.get(key, [])
    return value if isinstance(value, list) else []


def cmd_settings_input_root_list(as_json: bool) -> int:
    settings = load_settings()
    _print_payload(_root_list_payload(settings, "inputRoots"), as_json)
    return 0


def cmd_settings_input_root_add(
    *, root_id: str, path: Path, display_name: str | None, enabled: bool, as_json: bool
) -> int:
    settings = load_settings()
    rows = _root_list_payload(settings, "inputRoots")
    normalized_id = root_id.strip()
    if not normalized_id:
        raise ValueError("Input root id is required.")
    root_row = {
        "id": normalized_id,
        "displayName": display_name or normalized_id,
        "path": str(path),
        "enabled": enabled,
    }
    replaced = False
    for index, row in enumerate(rows):
        if str(row.get("id") or "").lower() == normalized_id.lower():
            rows[index] = root_row
            replaced = True
            break
    if not replaced:
        rows.append(root_row)
    settings["inputRoots"] = rows
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "inputRoots"), as_json)
    return 0


def cmd_settings_input_root_remove(root_id: str, as_json: bool) -> int:
    settings = load_settings()
    rows = [
        row
        for row in _root_list_payload(settings, "inputRoots")
        if str(row.get("id") or "").lower() != root_id.strip().lower()
    ]
    settings["inputRoots"] = rows
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "inputRoots"), as_json)
    return 0


def cmd_settings_input_root_clear(as_json: bool) -> int:
    settings = load_settings()
    settings["inputRoots"] = []
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "inputRoots"), as_json)
    return 0


def cmd_settings_output_root_list(as_json: bool) -> int:
    settings = load_settings()
    _print_payload(_root_list_payload(settings, "outputRoots"), as_json)
    return 0


def cmd_settings_output_root_set(
    *, root_id: str, path: Path, display_name: str | None, as_json: bool
) -> int:
    settings = load_settings()
    normalized_id = root_id.strip() or "runs"
    settings["outputRoots"] = [
        {
            "id": normalized_id,
            "displayName": display_name or normalized_id,
            "path": str(path),
            "enabled": True,
        }
    ]
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "outputRoots"), as_json)
    return 0


def cmd_jobs_list(as_json: bool) -> int:
    _print_payload(list_runs(), as_json)
    return 0


def cmd_jobs_show(job_id: str, as_json: bool) -> int:
    run_dir = find_run_dir(job_id)
    payload = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "request": json.loads(
            (run_dir / "request.json").read_text(encoding="utf-8-sig", errors="replace")
        ),
        "status": json.loads(
            (run_dir / "status.json").read_text(encoding="utf-8-sig", errors="replace")
        ),
        "result": json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8-sig", errors="replace")
        ),
    }
    _print_payload(payload, as_json)
    return 0


def cmd_jobs_create(
    *,
    files: list[Path],
    directories: list[Path],
    source_ids: list[str],
    output_root_id: str,
    language: str | None,
    ipa_backend: str | None,
    vad_profile: str | None,
    supplemental_context: str | None,
    supplemental_context_file: Path | None,
    ipa_only: bool,
    reprocess_duplicates: bool,
    queue_only: bool,
    as_json: bool,
) -> int:
    settings = load_settings()
    if language is not None:
        settings["uiLanguage"] = language
    supplemental_context_text = supplemental_context
    if supplemental_context_file is not None:
        supplemental_context_text = supplemental_context_file.read_text(
            encoding="utf-8-sig", errors="replace"
        )
    input_items = collect_input_items(
        settings=settings,
        files=files,
        directories=directories,
        source_ids=source_ids,
    )
    if not input_items:
        raise ValueError("No input audio files were selected.")

    job_id, run_dir = create_job(
        settings=settings,
        input_items=input_items,
        output_root_id=output_root_id,
        reprocess_duplicates=reprocess_duplicates,
        readable_text_enabled=not ipa_only,
        supplemental_context_text=supplemental_context_text,
        ipa_backend=ipa_backend,
        vad_profile=vad_profile,
    )

    payload: dict[str, object] = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "state": "pending",
        "input_count": len(input_items),
        "readable_text_enabled": not ipa_only,
        "ipa_backend": resolve_ipa_backend(ipa_backend or str(settings.get("ipaBackend") or "")),
        "vad_profile": resolve_vad_profile(vad_profile or str(settings.get("vadProfile") or "")),
        "queue_only": queue_only,
    }

    if not queue_only:
        from .processor import process_job

        process_job(run_dir)
        status = json.loads(
            (run_dir / "status.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        result = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        payload["state"] = status.get("state", "unknown")
        payload["status"] = status
        payload["result"] = result

    _print_payload(payload, as_json)
    return 0


def cmd_jobs_run(job_id: str, as_json: bool) -> int:
    from .processor import process_job

    run_dir = find_run_dir(job_id)
    process_job(run_dir)
    payload = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "status": json.loads(
            (run_dir / "status.json").read_text(encoding="utf-8-sig", errors="replace")
        ),
        "result": json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8-sig", errors="replace")
        ),
    }
    _print_payload(payload, as_json)
    return 0


def cmd_jobs_archive(job_id: str, output: Path | None, artifact_kind: str, as_json: bool) -> int:
    archive_path = build_run_archive(job_id, output=output, artifact_kind=artifact_kind)
    payload = {
        "job_id": job_id,
        "artifact_kind": artifact_kind,
        "archive_path": str(archive_path),
    }
    _print_payload(payload, as_json)
    return 0


def cmd_refresh(
    *,
    source_ids: list[str],
    output_root_id: str,
    language: str | None,
    ipa_backend: str | None,
    vad_profile: str | None,
    supplemental_context: str | None,
    supplemental_context_file: Path | None,
    ipa_only: bool,
    reprocess_duplicates: bool,
    queue_only: bool,
    as_json: bool,
) -> int:
    settings = load_settings()
    if language is not None:
        settings["uiLanguage"] = language
    supplemental_context_text = supplemental_context
    if supplemental_context_file is not None:
        supplemental_context_text = supplemental_context_file.read_text(
            encoding="utf-8-sig", errors="replace"
        )
    job_id, run_dir, summary = create_refresh_job(
        settings=settings,
        source_ids=source_ids,
        output_root_id=output_root_id,
        reprocess_duplicates=reprocess_duplicates,
        readable_text_enabled=not ipa_only,
        supplemental_context_text=supplemental_context_text,
        ipa_backend=ipa_backend,
        vad_profile=vad_profile,
    )
    payload: dict[str, object] = {
        "state": "skipped" if job_id is None else "pending",
        "job_id": job_id,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "readable_text_enabled": not ipa_only,
        "ipa_backend": resolve_ipa_backend(ipa_backend or str(settings.get("ipaBackend") or "")),
        "vad_profile": resolve_vad_profile(vad_profile or str(settings.get("vadProfile") or "")),
        "queue_only": queue_only,
        **summary,
    }
    if job_id is not None and run_dir is not None and not queue_only:
        from .processor import process_job

        process_job(run_dir)
        status = json.loads(
            (run_dir / "status.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        result = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        payload["state"] = status.get("state", "unknown")
        payload["status"] = status
        payload["result"] = result
    _print_payload(payload, as_json)
    return 0


def _format_metric(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def cmd_evaluate(
    *,
    prediction_path: Path | None,
    job_id: str | None,
    media_id: str | None,
    artifact_kind: str,
    reference_path: Path,
    output_dir: Path | None,
    as_json: bool,
) -> int:
    from .evaluation import (
        evaluate_turn_artifacts,
        normalize_evaluation_artifact_kind,
        resolve_job_prediction_path,
        write_evaluation_report,
    )

    if prediction_path is not None and job_id is not None:
        raise ValueError("Use either --prediction or --job-id, not both.")
    if prediction_path is None:
        if not job_id:
            raise ValueError("Either --prediction or --job-id is required.")
        run_dir = find_run_dir(job_id)
        normalized_artifact_kind = normalize_evaluation_artifact_kind(artifact_kind)
        prediction_path = resolve_job_prediction_path(
            run_dir=run_dir,
            media_id=media_id,
            artifact_kind=normalized_artifact_kind,
        )
        if output_dir is None:
            resolved_media_id = prediction_path.parents[1].name
            output_dir = run_dir / "evaluation" / f"{resolved_media_id}-{normalized_artifact_kind}"
    else:
        normalized_artifact_kind = normalize_evaluation_artifact_kind(artifact_kind)

    payload = evaluate_turn_artifacts(
        prediction_path=prediction_path,
        reference_path=reference_path,
    )
    payload["artifact_kind"] = normalized_artifact_kind
    if job_id:
        payload["job_id"] = job_id
    if media_id:
        payload["media_id"] = media_id
    if output_dir is not None:
        payload["report"] = write_evaluation_report(payload, output_dir)

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"prediction_turns: {payload['prediction_turns']}")
    print(f"reference_turns: {payload['reference_turns']}")
    text_metrics = payload["text"]
    ipa_metrics = payload["ipa"]
    speaker_metrics = payload["speaker"]
    print(f"text_cer: {_format_metric(text_metrics['cer'])}")
    print(f"ipa_error_rate: {_format_metric(ipa_metrics['error_rate'])}")
    print(f"speaker_label_accuracy: {_format_metric(speaker_metrics['label_accuracy'])}")
    print(f"speaker_time_mismatch_rate: {_format_metric(speaker_metrics['time_mismatch_rate'])}")
    if payload.get("report"):
        report = payload["report"]
        print(f"evaluation_json_path: {report['evaluation_json_path']}")
        print(f"evaluation_markdown_path: {report['evaluation_markdown_path']}")
    return 0


def main() -> int:
    assert_cli_runtime_allowed()
    args = parse_args()
    if args.command == "settings":
        if args.settings_command == "init":
            _print_payload(init_settings(), args.json)
            return 0
        if args.settings_command == "status":
            return cmd_settings_status(args.json)
        if args.settings_command == "save":
            token = args.token if args.token is not None else load_huggingface_token()
            return cmd_settings_save(
                token,
                args.terms_confirmed,
                args.compute_mode,
                args.language,
                args.ipa_backend,
                args.vad_profile,
                args.json,
            )
        if args.settings_command == "input-root":
            if args.input_root_command == "list":
                return cmd_settings_input_root_list(args.json)
            if args.input_root_command == "add":
                return cmd_settings_input_root_add(
                    root_id=args.id,
                    path=args.path,
                    display_name=args.display_name,
                    enabled=not args.disabled,
                    as_json=args.json,
                )
            if args.input_root_command == "remove":
                return cmd_settings_input_root_remove(args.id, args.json)
            if args.input_root_command == "clear":
                return cmd_settings_input_root_clear(args.json)
        if args.settings_command == "output-root":
            if args.output_root_command == "list":
                return cmd_settings_output_root_list(args.json)
            if args.output_root_command == "set":
                return cmd_settings_output_root_set(
                    root_id=args.id,
                    path=args.path,
                    display_name=args.display_name,
                    as_json=args.json,
                )
    if args.command == "jobs":
        if args.jobs_command == "list":
            return cmd_jobs_list(args.json)
        if args.jobs_command == "show":
            return cmd_jobs_show(args.job_id, args.json)
        if args.jobs_command == "create":
            return cmd_jobs_create(
                files=args.files,
                directories=args.directories,
                source_ids=args.source_ids,
                output_root_id=args.output_root_id,
                language=args.language,
                ipa_backend=args.ipa_backend,
                vad_profile=args.vad_profile,
                supplemental_context=args.supplemental_context,
                supplemental_context_file=args.supplemental_context_file,
                ipa_only=args.ipa_only,
                reprocess_duplicates=args.reprocess_duplicates,
                queue_only=args.queue_only,
                as_json=args.json,
            )
        if args.jobs_command == "run":
            return cmd_jobs_run(args.job_id, args.json)
        if args.jobs_command == "archive":
            return cmd_jobs_archive(args.job_id, args.output, args.artifact_kind, args.json)
    if args.command == "scan":
        return cmd_scan(args.config, args.output)
    if args.command == "refresh":
        return cmd_refresh(
            source_ids=args.source_ids,
            output_root_id=args.output_root_id,
            language=args.language,
            ipa_backend=args.ipa_backend,
            vad_profile=args.vad_profile,
            supplemental_context=args.supplemental_context,
            supplemental_context_file=args.supplemental_context_file,
            ipa_only=args.ipa_only,
            reprocess_duplicates=args.reprocess_duplicates,
            queue_only=args.queue_only,
            as_json=args.json,
        )
    if args.command == "evaluate":
        return cmd_evaluate(
            prediction_path=args.prediction,
            job_id=args.job_id,
            media_id=args.media_id,
            artifact_kind=args.artifact_kind,
            reference_path=args.reference,
            output_dir=args.output_dir,
            as_json=args.json,
        )
    if args.command == "run-job":
        return cmd_run_job(args.job_dir)
    if args.command == "daemon":
        return cmd_daemon(args.poll_interval)
    raise ValueError(f"Unsupported command: {args.command}")

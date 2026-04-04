from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import AppConfig, ChangeDetectionConfig, SourceDirectory, load_config
from .discovery import discover_audio
from .fs_utils import now_iso
from .job_store import (
    build_run_archive,
    collect_input_items,
    create_job,
    find_run_dir,
    list_runs,
    settings_snapshot,
)
from .settings import (
    load_huggingface_token,
    load_runtime_defaults,
    load_settings,
    save_huggingface_token,
    save_settings,
    save_worker_capabilities,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="audio2timeline worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    settings_parser = subparsers.add_parser("settings", help="Show or update local settings.")
    settings_subparsers = settings_parser.add_subparsers(dest="settings_command", required=True)
    settings_status = settings_subparsers.add_parser(
        "status", help="Show current settings readiness."
    )
    settings_status.add_argument("--json", action="store_true")
    settings_save = settings_subparsers.add_parser(
        "save", help="Save Hugging Face token and terms confirmation."
    )
    settings_save.add_argument("--token", type=str, required=False)
    settings_save.add_argument("--terms-confirmed", action="store_true")
    settings_save.add_argument("--compute-mode", choices=["cpu", "gpu"], required=False)
    settings_save.add_argument("--processing-quality", choices=["standard", "high"], required=False)
    settings_save.add_argument("--json", action="store_true")

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
    jobs_archive.add_argument("--json", action="store_true")

    scan_parser = subparsers.add_parser(
        "scan", help="Scan configured source directories for audio files."
    )
    scan_parser.add_argument("--config", type=Path, required=False)
    scan_parser.add_argument("--output", type=Path, required=False)

    compare_parser = subparsers.add_parser("compare-images", help="Compare two images.")
    compare_parser.add_argument("--config", type=Path, required=False)
    compare_parser.add_argument("--previous", type=Path, required=True)
    compare_parser.add_argument("--current", type=Path, required=True)

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
    defaults = load_runtime_defaults()
    return AppConfig(
        project_name="audio2timeline",
        source_directories=[
            SourceDirectory(
                name=str(row.get("id") or row.get("displayName") or "source"),
                path=str(row.get("path") or ""),
                recursive=True,
            )
            for row in defaults.get("inputRoots", [])
            if row.get("enabled", True) and row.get("path")
        ],
        output_root=str(
            defaults.get("outputRoots", [{}])[0].get("path") or "/shared/outputs/default"
        ),
        audio_extensions=[str(ext) for ext in defaults.get("audioExtensions", [])],
        change_detection=ChangeDetectionConfig(),
    )


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


def cmd_compare(config_path: Path | None, previous: Path, current: Path) -> int:
    from .change_detection import compare_images

    config = _load_app_config(config_path)
    result = compare_images(previous, current, config.change_detection)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
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
    terms_confirmed: bool,
    compute_mode: str | None,
    processing_quality: str | None,
    as_json: bool,
) -> int:
    settings = load_settings()
    if token is not None:
        save_huggingface_token(token)
    if compute_mode is not None:
        settings["computeMode"] = compute_mode
    if processing_quality is not None:
        settings["processingQuality"] = processing_quality
    settings["huggingfaceTermsConfirmed"] = terms_confirmed
    save_settings(settings)
    _print_payload(settings_snapshot(settings), as_json)
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
    reprocess_duplicates: bool,
    queue_only: bool,
    as_json: bool,
) -> int:
    settings = load_settings()
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
    )

    payload: dict[str, object] = {
        "job_id": job_id,
        "run_dir": str(run_dir),
        "state": "pending",
        "input_count": len(input_items),
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


def cmd_jobs_archive(job_id: str, output: Path | None, as_json: bool) -> int:
    archive_path = build_run_archive(job_id, output=output)
    payload = {
        "job_id": job_id,
        "archive_path": str(archive_path),
    }
    _print_payload(payload, as_json)
    return 0


def main() -> int:
    args = parse_args()
    if args.command == "settings":
        if args.settings_command == "status":
            return cmd_settings_status(args.json)
        if args.settings_command == "save":
            token = args.token if args.token is not None else load_huggingface_token()
            return cmd_settings_save(
                token,
                args.terms_confirmed,
                args.compute_mode,
                args.processing_quality,
                args.json,
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
                reprocess_duplicates=args.reprocess_duplicates,
                queue_only=args.queue_only,
                as_json=args.json,
            )
        if args.jobs_command == "run":
            return cmd_jobs_run(args.job_id, args.json)
        if args.jobs_command == "archive":
            return cmd_jobs_archive(args.job_id, args.output, args.json)
    if args.command == "scan":
        return cmd_scan(args.config, args.output)
    if args.command == "compare-images":
        return cmd_compare(args.config, args.previous, args.current)
    if args.command == "run-job":
        return cmd_run_job(args.job_dir)
    if args.command == "daemon":
        return cmd_daemon(args.poll_interval)
    raise ValueError(f"Unsupported command: {args.command}")

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import AppConfig, load_config
from .discovery import discover_audio
from .fs_utils import now_iso
from .runtime_guard import assert_cli_runtime_allowed
from .run_store import (
    app_config_from_settings,
    build_items_archive,
    create_refresh_run,
    list_items,
    list_audio_file_rows,
    list_runs,
    remove_items,
    settings_snapshot,
)
from .model_inventory import build_model_inventory
from .settings import (
    init_settings,
    load_huggingface_token,
    load_settings,
    save_settings,
    save_worker_capabilities,
    save_worker_heartbeat,
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
    settings_validate_token = settings_subparsers.add_parser(
        "validate-token", help="Validate the Hugging Face token used for local audio analysis."
    )
    settings_validate_token.add_argument("--token", type=str, required=False)
    settings_validate_token.add_argument("--json", action="store_true")
    settings_save = settings_subparsers.add_parser("save", help="Save local settings.")
    settings_save.add_argument("--token", type=str, required=False)
    settings_save.add_argument("--compute-mode", choices=["cpu", "gpu"], required=False)
    settings_save.add_argument("--json", action="store_true")
    inputs = settings_subparsers.add_parser(
        "inputs", help="Manage configured input directories."
    )
    inputs_subparsers = inputs.add_subparsers(dest="inputs_command", required=True)
    inputs_list = inputs_subparsers.add_parser("list", help="List input directories.")
    inputs_list.add_argument("--json", action="store_true")
    inputs_add = inputs_subparsers.add_parser("add", help="Add an input directory.")
    inputs_add.add_argument("path", type=Path)
    inputs_add.add_argument("--json", action="store_true")
    inputs_remove = inputs_subparsers.add_parser("remove", help="Remove an input directory.")
    inputs_remove.add_argument("id")
    inputs_remove.add_argument("--json", action="store_true")
    inputs_clear = inputs_subparsers.add_parser("clear", help="Remove all input directories.")
    inputs_clear.add_argument("--json", action="store_true")
    master = settings_subparsers.add_parser(
        "master", help="Manage the single master output directory."
    )
    master_subparsers = master.add_subparsers(dest="master_command", required=True)
    master_show = master_subparsers.add_parser("show", help="Show the master output directory.")
    master_show.add_argument("--json", action="store_true")
    master_set = master_subparsers.add_parser("set", help="Set the master output directory.")
    master_set.add_argument("path", type=Path)
    master_set.add_argument("--json", action="store_true")

    runs_parser = subparsers.add_parser("runs", help="Inspect past item refresh runs.")
    runs_subparsers = runs_parser.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_subparsers.add_parser("list", help="List runs in the configured output root.")
    runs_list.add_argument("--json", action="store_true")
    runs_show = runs_subparsers.add_parser("show", help="Show one run request/status/result.")
    runs_show.add_argument("--run-id", type=str, required=True)
    runs_show.add_argument("--json", action="store_true")

    files_parser = subparsers.add_parser(
        "files", help="Inspect source audio files in configured input directories."
    )
    files_subparsers = files_parser.add_subparsers(dest="files_command", required=True)
    files_list = files_subparsers.add_parser("list", help="List configured audio files.")
    files_list.add_argument("--probe", action="store_true")
    files_list.add_argument("--json", action="store_true")
    files_scan = files_subparsers.add_parser(
        "scan", help="Scan configured source directories and return raw discovery rows."
    )
    files_scan.add_argument("--config", type=Path, required=False)
    files_scan.add_argument("--output", type=Path, required=False)
    files_scan.add_argument("--json", action="store_true")

    items_parser = subparsers.add_parser(
        "items", help="Manage TimelineForAudio analysis items and generated data."
    )
    items_subparsers = items_parser.add_subparsers(dest="items_command", required=True)
    items_list = items_subparsers.add_parser("list", help="List managed analysis items.")
    items_list.add_argument("--json", action="store_true")
    items_refresh = items_subparsers.add_parser(
        "refresh", help="Read configured input directories and process changed audio only."
    )
    items_refresh.add_argument("--source-id", dest="source_ids", action="append", default=[])
    items_refresh.add_argument("--reprocess-duplicates", action="store_true")
    items_refresh.add_argument("--max-items", "--limit", dest="max_items", type=int, required=False)
    items_refresh.add_argument("--queue-only", action="store_true")
    items_refresh.add_argument("--json", action="store_true")
    items_remove = items_subparsers.add_parser(
        "remove", help="Remove managed item data without deleting source audio."
    )
    items_remove.add_argument("--item-id", required=True)
    items_remove.add_argument("--dry-run", action="store_true")
    items_remove.add_argument("--json", action="store_true")
    items_download = items_subparsers.add_parser(
        "download", help="Create a ZIP package for one or more managed items."
    )
    items_download.add_argument("--item-id", required=False)
    items_download.add_argument("--all", action="store_true")
    items_download.add_argument("--output", type=Path, required=False)
    items_download.add_argument("--json", action="store_true")

    models_parser = subparsers.add_parser(
        "models", help="List models and model-like components used by the current pipeline."
    )
    models_subparsers = models_parser.add_subparsers(dest="models_command", required=True)
    models_list = models_subparsers.add_parser("list", help="List configured model inventory.")
    models_list.add_argument(
        "--include-remote",
        "--remote",
        action="store_true",
        help="Fetch Hugging Face metadata such as license and gated status.",
    )
    models_list.add_argument("--output", type=Path, required=False)
    models_list.add_argument("--json", action="store_true")

    run_parser = subparsers.add_parser("process-run", help="Process one specific internal run directory.")
    run_parser.add_argument("--run-dir", type=Path, required=True)

    daemon_parser = subparsers.add_parser(
        "daemon", help="Poll output roots and process pending runs."
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


def cmd_scan(config_path: Path | None, output: Path | None, as_json: bool) -> int:
    payload = discover_audio(_load_app_config(config_path))
    if output:
        write_json(output, payload)
    _print_payload(payload, as_json)
    return 0


def cmd_files_list(*, include_probe: bool, as_json: bool) -> int:
    rows = list_audio_file_rows(include_probe=include_probe)
    _print_payload(rows, as_json)
    return 0


def _split_cli_ids(value: str) -> list[str]:
    rows: list[str] = []
    for part in str(value or "").replace("\n", ",").split(","):
        normalized = part.strip()
        if normalized:
            rows.append(normalized)
    return rows


def cmd_items_list(*, as_json: bool) -> int:
    rows = list_items()
    _print_payload(rows, as_json)
    return 0


def cmd_items_remove(
    *,
    item_id_value: str,
    dry_run: bool,
    as_json: bool,
) -> int:
    payload = remove_items(
        item_ids=_split_cli_ids(item_id_value),
        dry_run=dry_run,
    )
    _print_payload(payload, as_json)
    return 0


def cmd_items_download(
    *,
    item_id_value: str | None,
    include_all: bool,
    output: Path | None,
    as_json: bool,
) -> int:
    if include_all and item_id_value:
        raise ValueError("Use either --all or --item-id, not both.")
    if include_all:
        item_ids = [
            str(row.get("item_id") or "")
            for row in list_items()
            if str(row.get("status") or "") == "available" and str(row.get("item_id") or "")
        ]
    else:
        item_ids = _split_cli_ids(item_id_value or "")
    if not item_ids:
        raise ValueError("At least one available item id is required.")
    archive_path = build_items_archive(
        item_ids=item_ids,
        output=output,
    )
    payload = {
        "archive_path": str(archive_path),
        "item_ids": item_ids,
        "all": include_all,
    }
    _print_payload(payload, as_json)
    return 0


def cmd_models_list(*, include_remote: bool, output: Path | None, as_json: bool) -> int:
    payload = build_model_inventory(
        settings=load_settings(),
        include_remote=include_remote,
    )
    if output:
        write_json(output, payload)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    print(f"pipeline_version: {payload['pipeline']['pipeline_version']}")
    print(f"compute_mode: {payload['pipeline']['compute_mode']}")
    print(f"generation_signature: {payload['pipeline']['generation_signature']}")
    for row in payload["models"]:
        print(
            f"{row['role']}: {row['model_id']} | "
            f"{row['source']} | {row['backend']} | required={row['required']}"
        )
        if row.get("url"):
            print(f"  url: {row['url']}")
        remote = row.get("huggingface")
        if isinstance(remote, dict):
            license_value = remote.get("license") or "unknown"
            gated = remote.get("gated")
            print(f"  hf: status={remote.get('remote_status')} license={license_value} gated={gated}")
    return 0


def cmd_process_run(run_dir: Path) -> int:
    from .processor import process_run

    process_run(run_dir)
    return 0


def cmd_daemon(poll_interval: int) -> int:
    from .processor import process_run

    _write_worker_capabilities()
    _start_worker_heartbeat()
    while True:
        found = process_run()
        if not found:
            time.sleep(max(1, poll_interval))
    return 0


def _start_worker_heartbeat(interval_seconds: int = 5) -> None:
    def heartbeat_loop() -> None:
        while True:
            save_worker_heartbeat(
                {
                    "schema_version": 1,
                    "state": "running",
                    "updated_at": now_iso(),
                    "pid": os.getpid(),
                    "worker_flavor": os.getenv("TIMELINE_FOR_AUDIO_WORKER_FLAVOR", "cpu"),
                }
            )
            time.sleep(max(1, interval_seconds))

    thread = threading.Thread(target=heartbeat_loop, name="worker-heartbeat", daemon=True)
    thread.start()


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
            print("No rows found.")
            return
        for row in payload:
            if "item_id" in row:
                print(
                    f"{row.get('item_id')} | {row.get('status')} | "
                    f"{row.get('source_file_name', '')} | {row.get('run_id', '')}"
                )
            elif "file_name" in row:
                print(
                    f"{row.get('status')} | {row.get('file_name')} | "
                    f"{row.get('source_file_identity', '')}"
                )
            elif "run_id" in row:
                print(
                    f"{row.get('run_id')} | {row.get('state')} | "
                    f"{row.get('items_done', 0)}/{row.get('items_total', 0)} | "
                    f"{row.get('current_stage', '')} | {row.get('run_dir', '')}"
                )
            else:
                print(json.dumps(row, ensure_ascii=False))
        return

    for key, value in payload.items():
        print(f"{key}: {value}")


def cmd_settings_status(as_json: bool) -> int:
    _print_payload(settings_snapshot(), as_json)
    return 0


def _validate_token_value(token: str | None) -> dict[str, object]:
    value = str(token or "").strip()
    if not value:
        return {
            "valid": False,
            "status": "missing",
        }
    if not value.startswith("hf_") or len(value) < 20:
        return {
            "valid": False,
            "status": "invalid_format",
        }

    request = urllib.request.Request(
        "https://huggingface.co/api/whoami-v2",
        headers={
            "Authorization": f"Bearer {value}",
            "User-Agent": "TimelineForAudio/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            name = payload.get("name") or payload.get("fullname") or "Hugging Face account"
            return {
                "valid": True,
                "status": "ok",
                "account_name": name,
            }
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return {
                "valid": False,
                "status": "rejected",
                "http_status": exc.code,
            }
        return {
            "valid": False,
            "status": "remote_error",
            "http_status": exc.code,
        }
    except Exception as exc:
        return {
            "valid": False,
            "status": "connection_error",
            "error": str(exc),
        }


def cmd_settings_validate_token(token: str | None, as_json: bool) -> int:
    value = token if token is not None else load_huggingface_token()
    payload = _validate_token_value(value)
    _print_payload(payload, as_json)
    return 0


def cmd_settings_save(
    token: str | None,
    compute_mode: str | None,
    as_json: bool,
) -> int:
    settings = load_settings()
    if token is not None:
        settings["huggingfaceToken"] = token.strip() if token and token.strip() else ""
    if compute_mode is not None:
        settings["computeMode"] = compute_mode
    save_settings(settings)
    _print_payload(settings_snapshot(settings), as_json)
    return 0


def _root_list_payload(settings: dict[str, object], key: str) -> list[dict[str, object]]:
    value = settings.get(key, [])
    return value if isinstance(value, list) else []


def _master_payload(settings: dict[str, object]) -> dict[str, object] | None:
    value = settings.get("outputRoot")
    return value if isinstance(value, dict) and value.get("path") else None


def cmd_settings_inputs_list(as_json: bool) -> int:
    settings = load_settings()
    _print_payload(_root_list_payload(settings, "inputRoots"), as_json)
    return 0


def _new_input_root_id(rows: list[dict[str, object]]) -> str:
    existing = {str(row.get("id") or "").lower() for row in rows}
    while True:
        candidate = f"input-{os.urandom(3).hex()}"
        if candidate.lower() not in existing:
            return candidate


def cmd_settings_inputs_add(*, path: Path, as_json: bool) -> int:
    settings = load_settings()
    rows = _root_list_payload(settings, "inputRoots")
    normalized_path = str(path)
    for row in rows:
        if str(row.get("path") or "").strip().lower() == normalized_path.strip().lower():
            _print_payload(_root_list_payload(settings, "inputRoots"), as_json)
            return 0
    normalized_id = _new_input_root_id(rows)
    root_row = {
        "id": normalized_id,
        "path": normalized_path,
    }
    rows.append(root_row)
    settings["inputRoots"] = rows
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "inputRoots"), as_json)
    return 0


def cmd_settings_inputs_remove(root_id: str, as_json: bool) -> int:
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


def cmd_settings_inputs_clear(as_json: bool) -> int:
    settings = load_settings()
    settings["inputRoots"] = []
    save_settings(settings)
    _print_payload(_root_list_payload(load_settings(), "inputRoots"), as_json)
    return 0


def cmd_settings_master_show(as_json: bool) -> int:
    settings = load_settings()
    _print_payload(_master_payload(settings) or {}, as_json)
    return 0


def cmd_settings_master_set(*, path: Path, as_json: bool) -> int:
    settings = load_settings()
    settings["outputRoot"] = {
        "path": str(path),
    }
    save_settings(settings)
    _print_payload(_master_payload(load_settings()) or {}, as_json)
    return 0


def _rename_internal_id_to_run_id(payload: object) -> object:
    if isinstance(payload, dict):
        renamed = {
            key: _rename_internal_id_to_run_id(value) for key, value in payload.items()
        }
        return renamed
    if isinstance(payload, list):
        return [_rename_internal_id_to_run_id(item) for item in payload]
    return payload


def cmd_runs_list(as_json: bool) -> int:
    rows = _rename_internal_id_to_run_id(list_runs())
    _print_payload(rows, as_json)
    return 0


def cmd_runs_show(run_id: str, as_json: bool) -> int:
    run_dir = find_run_dir(run_id)
    payload = {
        "run_id": run_id,
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
    performance_path = run_dir / "RUN_PERFORMANCE.json"
    if performance_path.exists():
        payload["performance"] = json.loads(
            performance_path.read_text(encoding="utf-8-sig", errors="replace")
        )
    _print_payload(_rename_internal_id_to_run_id(payload), as_json)
    return 0


def cmd_items_refresh(
    *,
    source_ids: list[str],
    output_root_id: str,
    reprocess_duplicates: bool,
    max_items: int | None,
    queue_only: bool,
    as_json: bool,
) -> int:
    settings = load_settings()
    run_id, run_dir, summary = create_refresh_run(
        settings=settings,
        source_ids=source_ids,
        output_root_id=output_root_id,
        reprocess_duplicates=reprocess_duplicates,
        max_items=max_items,
    )
    summary = _rename_internal_id_to_run_id(summary)
    payload: dict[str, object] = {
        "state": "skipped" if run_id is None else "pending",
        "run_id": run_id,
        "run_dir": str(run_dir) if run_dir is not None else None,
        "artifact": "timeline",
        "queue_only": queue_only,
        **summary,
    }
    if run_id is not None and run_dir is not None and not queue_only:
        from .processor import process_run

        process_run(run_dir)
        status = json.loads(
            (run_dir / "status.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        result = json.loads(
            (run_dir / "result.json").read_text(encoding="utf-8-sig", errors="replace")
        )
        payload["state"] = status.get("state", "unknown")
        payload["status"] = _rename_internal_id_to_run_id(status)
        payload["result"] = _rename_internal_id_to_run_id(result)
    _print_payload(_rename_internal_id_to_run_id(payload), as_json)
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
        if args.settings_command == "validate-token":
            return cmd_settings_validate_token(args.token, args.json)
        if args.settings_command == "save":
            return cmd_settings_save(
                args.token,
                args.compute_mode,
                args.json,
            )
        if args.settings_command == "inputs":
            if args.inputs_command == "list":
                return cmd_settings_inputs_list(args.json)
            if args.inputs_command == "add":
                return cmd_settings_inputs_add(path=args.path, as_json=args.json)
            if args.inputs_command == "remove":
                return cmd_settings_inputs_remove(args.id, args.json)
            if args.inputs_command == "clear":
                return cmd_settings_inputs_clear(args.json)
        if args.settings_command == "master":
            if args.master_command == "show":
                return cmd_settings_master_show(args.json)
            if args.master_command == "set":
                return cmd_settings_master_set(path=args.path, as_json=args.json)
    if args.command == "runs":
        if args.runs_command == "list":
            return cmd_runs_list(args.json)
        if args.runs_command == "show":
            return cmd_runs_show(args.run_id, args.json)
    if args.command == "files":
        if args.files_command == "list":
            return cmd_files_list(include_probe=args.probe, as_json=args.json)
        if args.files_command == "scan":
            return cmd_scan(args.config, args.output, args.json)
    if args.command == "items":
        if args.items_command == "list":
            return cmd_items_list(as_json=args.json)
        if args.items_command == "refresh":
            return cmd_items_refresh(
                source_ids=args.source_ids,
                output_root_id="master",
                reprocess_duplicates=args.reprocess_duplicates,
                max_items=args.max_items,
                queue_only=args.queue_only,
                as_json=args.json,
            )
        if args.items_command == "remove":
            return cmd_items_remove(
                item_id_value=args.item_id,
                dry_run=args.dry_run,
                as_json=args.json,
            )
        if args.items_command == "download":
            return cmd_items_download(
                item_id_value=args.item_id,
                include_all=args.all,
                output=args.output,
                as_json=args.json,
            )
    if args.command == "models":
        if args.models_command == "list":
            return cmd_models_list(
                include_remote=args.include_remote,
                output=args.output,
                as_json=args.json,
            )
    if args.command == "process-run":
        return cmd_process_run(args.run_dir)
    if args.command == "daemon":
        return cmd_daemon(args.poll_interval)
    raise ValueError(f"Unsupported command: {args.command}")

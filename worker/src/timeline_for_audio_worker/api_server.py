from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .model_inventory import build_model_inventory
from .run_store import build_items_archive
from .run_store import create_refresh_run
from .run_store import find_run_dir
from .run_store import get_active_run
from .run_store import list_audio_file_page
from .run_store import list_items
from .run_store import list_items_page
from .run_store import list_runs
from .run_store import remove_items
from .run_store import settings_snapshot
from .settings import init_settings
from .settings import load_settings
from .settings import save_settings
from .settings import configured_path
from .settings import configured_path_to_host_text
from .worker_runtime import start_worker_heartbeat
from .worker_runtime import write_worker_capabilities
from .processor import request_run_cancel


def handle_request(method: str, path: str, request: dict[str, Any] | None) -> tuple[int, Any]:
    route = path.rstrip("/") or "/"
    if method == "GET" and route == "/health":
        return HTTPStatus.OK, True
    if method == "GET" and route == "/jobs":
        return HTTPStatus.OK, jobs_list_payload()
    if method == "GET" and route == "/jobs/active":
        return HTTPStatus.OK, jobs_active_payload()
    if method == "GET" and route.startswith("/jobs/"):
        return job_response(job_status_payload(unquote(route.removeprefix("/jobs/"))))
    if method != "POST":
        return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")

    try:
        payload = request or {}
        if route == "/jobs":
            return HTTPStatus.OK, jobs_start_payload(payload)
        if route.startswith("/jobs/") and route.endswith("/cancel"):
            job_id = unquote(route[len("/jobs/") : -len("/cancel")]).strip()
            return job_response(jobs_cancel_payload(job_id))
        if route == "/settings/init":
            return HTTPStatus.OK, init_settings()
        if route == "/settings/status":
            return HTTPStatus.OK, settings_snapshot()
        if route == "/settings/save":
            return HTTPStatus.OK, settings_save_payload(payload)
        if route == "/files/list":
            return HTTPStatus.OK, files_list_payload(payload)
        if route == "/items/list":
            return HTTPStatus.OK, items_list_payload(payload)
        if route == "/items/refresh":
            return HTTPStatus.OK, items_refresh_payload(payload)
        if route == "/items/remove":
            return HTTPStatus.OK, items_remove_payload(payload)
        if route == "/items/download":
            return HTTPStatus.OK, items_download_payload(payload)
        if route == "/models/list":
            return HTTPStatus.OK, models_list_payload(payload)
    except Exception as exc:
        return HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)

    return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")


def settings_save_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    token = get_string_any(request, ["token", "huggingFaceToken", "huggingfaceToken"])
    compute_mode = get_string_any(request, ["computeMode", "compute_mode"])
    if token:
        settings["huggingFaceToken"] = token.strip()
    if compute_mode:
        settings["computeMode"] = compute_mode
    save_settings(settings)
    return settings_snapshot(settings)


def files_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    return list_audio_file_page(
        include_probe=get_bool_any(request, ["probe"], False),
        page=get_optional_positive_int(request, ["page"]),
        page_size=get_optional_positive_int(request, ["pageSize", "page_size"]),
    )


def items_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    return list_items_page(
        page=get_optional_positive_int(request, ["page"]),
        page_size=get_optional_positive_int(request, ["pageSize", "page_size"]),
    )


def items_refresh_payload(request: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    queue_only = get_bool_any(request, ["queueOnly", "queue_only"], True)
    run_id, run_dir, summary = create_refresh_run(
        settings=settings,
        source_ids=get_string_array_any(request, ["sourceIds", "source_ids", "inputRoots", "input_roots"]),
        output_root_id="master",
        reprocess_duplicates=get_bool_any(request, ["reprocessDuplicates", "reprocess_duplicates"], False),
        max_items=get_optional_positive_int(request, ["maxItems", "max_items", "limit"]),
    )
    response: dict[str, Any] = {
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
        response["status"] = read_json_file(run_dir / "status.json")
        response["result"] = read_json_file(run_dir / "result.json")
        response["state"] = str(response["status"].get("state", "unknown"))
    return response


def jobs_start_payload(request: dict[str, Any]) -> dict[str, Any]:
    job_type = get_string_any(request, ["type", "jobType", "job_type"]) or "refresh"
    if job_type != "refresh":
        raise ValueError(f"Unsupported job type: {job_type}")

    settings = load_settings()
    active = get_active_run(settings)
    if active:
        return job_status_payload(str(active.get("run_id") or ""), settings=settings)

    options = request.get("options") if isinstance(request.get("options"), dict) else request
    run_id, run_dir, summary = create_refresh_run(
        settings=settings,
        source_ids=get_string_array_any(options, ["sourceIds", "source_ids", "inputRoots", "input_roots"]),
        output_root_id="master",
        reprocess_duplicates=get_bool_any(options, ["reprocessDuplicates", "reprocess_duplicates"], False),
        max_items=get_optional_positive_int(options, ["maxItems", "max_items", "limit"]),
    )
    if run_id is None or run_dir is None:
        return no_job_payload(
            message="No changed audio files were found.",
            result={
                "state": "skipped_no_changes",
                **summary,
            },
        )
    return job_status_payload(run_id, settings=settings, fallback_result={**summary, "run_id": run_id, "run_dir": str(run_dir)})


def jobs_list_payload() -> dict[str, Any]:
    runs = list_runs()
    return {
        "schemaVersion": "timeline.product_jobs.v1",
        "productId": "audio",
        "productName": "TimelineForAudio",
        "activeJobId": (get_active_run() or {}).get("run_id", ""),
        "count": len(runs),
        "jobs": runs,
    }


def jobs_active_payload() -> dict[str, Any]:
    active = get_active_run()
    if not active:
        return no_job_payload(message="No active audio job.", state="none", progress_percent=0.0)
    return job_status_payload(str(active.get("run_id") or ""))


def jobs_cancel_payload(job_id: str) -> dict[str, Any]:
    job_id = job_id.strip()
    if not job_id:
        return error_payload("Job id is required.", "ValueError") | {"ok": False}

    try:
        run_dir = find_run_dir(job_id)
    except Exception as exc:
        return error_payload(str(exc), exc.__class__.__name__) | {"ok": False}

    status = job_status_payload(job_id)
    if str(status.get("state") or "").lower() not in {"queued", "running", "canceling"}:
        return status

    request_run_cancel(run_dir, "Audio refresh cancellation was requested.")
    return job_status_payload(job_id)


def job_response(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if payload.get("ok") is False:
        return HTTPStatus.NOT_FOUND, payload
    return HTTPStatus.OK, payload


def job_status_payload(
    job_id: str,
    *,
    settings: dict[str, Any] | None = None,
    fallback_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = job_id.strip()
    if not job_id:
        return error_payload("Job id is required.", "ValueError") | {"ok": False}

    try:
        run_dir = find_run_dir(job_id, settings)
    except Exception as exc:
        return error_payload(str(exc), exc.__class__.__name__) | {"ok": False}

    status = read_json_file_or_empty(run_dir / "status.json")
    result = read_json_file_or_empty(run_dir / "result.json") or fallback_result
    state = normalize_job_state(str(status.get("state") or (result or {}).get("state") or "unknown"))
    stage = str(status.get("current_stage") or "")
    message = str(status.get("message") or "")
    total = int(status.get("items_total") or 0)
    current = (
        int(status.get("items_done") or 0)
        + int(status.get("items_skipped") or 0)
        + int(status.get("items_failed") or 0)
    )
    progress_percent = float(status.get("progress_percent") or (100.0 if state in {"completed", "completed_with_errors"} else 0.0))
    error = message if state in {"failed", "completed_with_errors", "interrupted"} else None
    return {
        "schemaVersion": "timeline.product_job.v1",
        "productId": "audio",
        "productName": "TimelineForAudio",
        "type": "refresh",
        "jobId": job_id,
        "state": state,
        "phase": stage,
        "stage": stage,
        "message": message,
        "progress": {
            "percent": round(max(0.0, min(100.0, progress_percent)), 2),
            "current": current,
            "total": total,
            "unit": "files",
            "currentItem": str(status.get("current_item") or ""),
            "estimatedRemainingSeconds": status.get("estimated_remaining_sec"),
        },
        "startedAt": str(status.get("started_at") or ""),
        "updatedAt": str(status.get("updated_at") or ""),
        "completedAt": str(status.get("completed_at") or ""),
        "error": error,
        "warnings": status.get("warnings") if isinstance(status.get("warnings"), list) else [],
        "result": result,
    }


def no_job_payload(
    *,
    message: str,
    state: str = "completed",
    progress_percent: float = 100.0,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": "timeline.product_job.v1",
        "productId": "audio",
        "productName": "TimelineForAudio",
        "type": "refresh",
        "jobId": "",
        "state": state,
        "phase": "completed" if state == "completed" else "",
        "stage": "completed" if state == "completed" else "",
        "message": message,
        "progress": {
            "percent": progress_percent,
            "current": 0,
            "total": 0,
            "unit": "files",
            "currentItem": "",
            "estimatedRemainingSeconds": None,
        },
        "startedAt": "",
        "updatedAt": "",
        "completedAt": "",
        "error": None,
        "warnings": [],
        "result": result,
    }


def normalize_job_state(state: str) -> str:
    lowered = state.strip().lower()
    if lowered == "pending":
        return "queued"
    if lowered in {"running", "queued", "canceling", "canceled", "completed", "completed_with_errors", "failed", "interrupted"}:
        return lowered
    if lowered == "cancelled":
        return "canceled"
    if lowered in {"skipped", "skipped_no_changes"}:
        return "completed"
    return lowered or "unknown"


def items_remove_payload(request: dict[str, Any]) -> dict[str, Any]:
    item_ids = get_item_ids(request)
    if not item_ids:
        raise ValueError("At least one item id is required.")
    return remove_items(item_ids=item_ids, dry_run=get_bool_any(request, ["dryRun", "dry_run"], False))


def items_download_payload(request: dict[str, Any]) -> dict[str, Any]:
    item_ids = get_item_ids(request)
    if not item_ids:
        item_ids = [
            str(row.get("item_id") or "")
            for row in list_items()
            if str(row.get("status") or "") == "available" and str(row.get("item_id") or "")
        ]
    if not item_ids:
        raise ValueError("At least one available item id is required.")
    output = get_string_any(request, ["outputPath", "output", "to", "destinationPath"])
    archive_path = build_items_archive(
        item_ids=item_ids,
        output=configured_path(output) if output else None,
    )
    return {"archive_path": configured_path_to_host_text(archive_path), "item_ids": item_ids}


def models_list_payload(request: dict[str, Any]) -> dict[str, Any]:
    output = get_string_any(request, ["outputPath", "output"])
    payload = build_model_inventory(
        settings=load_settings(),
        include_remote=get_bool_any(request, ["includeRemote", "include_remote", "remote"], False),
    )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def read_json_file_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json_file(path)


def get_item_ids(request: dict[str, Any]) -> list[str]:
    values = get_string_array_any(request, ["itemIds", "item_ids", "itemId", "item_id"])
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            stripped = part.strip()
            if stripped and stripped not in result:
                result.append(stripped)
    return result


def get_optional_positive_int(request: dict[str, Any], names: list[str]) -> int | None:
    for name in names:
        value = get_node(request, name)
        if value is None:
            continue
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, str):
            try:
                parsed = int(value)
            except ValueError:
                continue
            return parsed if parsed > 0 else None
    return None


def get_bool_any(request: dict[str, Any], names: list[str], fallback: bool) -> bool:
    for name in names:
        value = get_node(request, name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
    return fallback


def get_string_any(request: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = get_node(request, name)
        if value is None:
            continue
        text = convert_json_text(value)
        if text:
            return text
    return ""


def get_string_array_any(request: dict[str, Any], names: list[str]) -> list[str]:
    for name in names:
        values = get_string_array(request, name)
        if values:
            return values
    return []


def get_string_array(request: dict[str, Any], name: str) -> list[str]:
    value = get_node(request, name)
    if value is None:
        return []
    if isinstance(value, list):
        return [convert_json_text(item) for item in value if convert_json_text(item)]
    text = convert_json_text(value)
    if not text:
        return []
    return [part.strip() for part in text.replace("\r", ",").replace("\n", ",").split(",") if part.strip()]


def get_node(request: dict[str, Any], name: str) -> Any:
    if name in request:
        return request[name]
    lowered = name.lower()
    for key, value in request.items():
        if key.lower() == lowered:
            return value
    return None


def convert_json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False).strip()


def error_payload(message: str, error_type: str = "Error") -> dict[str, Any]:
    return {"ok": False, "error": {"type": error_type, "message": message}}


def start_background_daemon(poll_interval: int) -> None:
    from .processor import process_run

    def loop() -> None:
        write_worker_capabilities()
        start_worker_heartbeat()
        while True:
            found = process_run()
            if not found:
                time.sleep(max(1, poll_interval))

    thread = threading.Thread(target=loop, name="audio-worker-daemon", daemon=True)
    thread.start()


class TimelineForAudioApiHandler(BaseHTTPRequestHandler):
    server_version = "TimelineForAudioWorkerApi/1.0"

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _handle(self) -> None:
        try:
            request = self._read_json()
            status_code, payload = handle_request(self.command, self.path.split("?", 1)[0], request)
        except Exception as exc:
            status_code, payload = HTTPStatus.INTERNAL_SERVER_ERROR, error_payload(str(exc), exc.__class__.__name__)
        self._write_json(status_code, payload)

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        if not raw.strip():
            return None
        loaded = json.loads(raw.decode("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("JSON request body must be an object.")
        return loaded

    def _write_json(self, status_code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status_code))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    host = os.environ.get("TIMELINE_FOR_AUDIO_API_BIND_HOST", "0.0.0.0")
    port = int(os.environ.get("TIMELINE_FOR_AUDIO_API_BIND_PORT", "8080"))
    poll_interval = int(os.environ.get("TIMELINE_FOR_AUDIO_WORKER_POLL_INTERVAL", "5"))
    start_background_daemon(poll_interval)
    server = ThreadingHTTPServer((host, port), TimelineForAudioApiHandler)
    print(f"TimelineForAudio worker API listening on http://{host}:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

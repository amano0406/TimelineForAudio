from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .model_inventory import build_model_inventory
from .run_store import build_items_archive
from .run_store import create_refresh_run
from .run_store import list_audio_file_page
from .run_store import list_items
from .run_store import list_items_page
from .run_store import remove_items
from .run_store import settings_snapshot
from .settings import init_settings
from .settings import load_settings
from .settings import save_settings
from .worker_runtime import start_worker_heartbeat
from .worker_runtime import write_worker_capabilities


def handle_request(method: str, path: str, request: dict[str, Any] | None) -> tuple[int, Any]:
    route = path.rstrip("/") or "/"
    if method == "GET" and route == "/health":
        return HTTPStatus.OK, True
    if method != "POST":
        return HTTPStatus.NOT_FOUND, error_payload(f"Endpoint not found: {method} {path}")

    try:
        payload = request or {}
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
    archive_path = build_items_archive(item_ids=item_ids, output=Path(output) if output else None)
    return {"archive_path": str(archive_path), "item_ids": item_ids}


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

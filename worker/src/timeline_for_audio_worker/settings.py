from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

_WINDOWS_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
_PATH_MAPPINGS_ENV = "TIMELINE_FOR_AUDIO_PATH_MAPPINGS"
_DEFAULT_AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".aac", ".flac"]
_INSTANCE_NAME_RE = re.compile(r"[^a-z0-9-]+")
_DEFAULT_API_PORT = 19100
_TOKEN_KEY = "huggingFaceToken"
_LEGACY_TOKEN_KEY = "huggingfaceToken"


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_appdata_root() -> Path:
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "TimelineForAudio"
    return Path.home() / ".timeline-for-audio"


def appdata_root() -> Path:
    return Path(os.getenv("TIMELINE_FOR_AUDIO_APPDATA_ROOT", str(_default_appdata_root())))


def uploads_root() -> Path:
    return Path(os.getenv("TIMELINE_FOR_AUDIO_UPLOADS_ROOT", str(appdata_root() / "uploads")))


def outputs_root() -> Path:
    return Path(os.getenv("TIMELINE_FOR_AUDIO_OUTPUTS_ROOT", str(appdata_root() / "outputs")))


def runtime_defaults_path() -> Path:
    return Path(os.getenv("TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS", "/app/config/runtime.defaults.json"))


def load_runtime_defaults() -> dict[str, Any]:
    path = runtime_defaults_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def settings_example_path() -> Path:
    return Path(
        os.getenv(
            "TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH",
            str(project_root() / "settings.example.json"),
        )
    )


def settings_path() -> Path:
    return Path(
        os.getenv(
            "TIMELINE_FOR_AUDIO_SETTINGS_PATH",
            str(project_root() / "settings.json"),
        )
    )


def worker_capabilities_path() -> Path:
    return appdata_root() / "worker-capabilities.json"


def worker_heartbeat_path() -> Path:
    return appdata_root() / "worker-heartbeat.json"


def configured_path(value: str | Path) -> Path:
    text = str(value or "").strip()
    mapped = _map_configured_path(text)
    if mapped is not None:
        return mapped
    match = _WINDOWS_DRIVE_RE.match(text)
    if match and os.name != "nt":
        drive = match.group("drive").lower()
        rest = match.group("rest").replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return Path(text).expanduser()


def configured_path_to_host_text(value: str | Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized_text = text.replace("\\", "/").rstrip("/")
    for row in sorted(_path_mappings(), key=lambda item: len(item["container"]), reverse=True):
        container_key = row["container"].replace("\\", "/").rstrip("/")
        if not container_key:
            continue
        if normalized_text == container_key:
            return row["host"]
        if normalized_text.startswith(container_key + "/"):
            relative = normalized_text[len(container_key) + 1 :]
            return _join_host_path(row["host"], relative)
    return text


def _normalize_mapping_key(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    if os.name == "nt":
        return normalized.lower()
    if _WINDOWS_DRIVE_RE.match(str(value or "").strip()):
        return normalized.lower()
    return normalized


def _path_mappings() -> list[dict[str, str]]:
    raw = os.getenv(_PATH_MAPPINGS_ENV)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, str]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        host = str(row.get("host") or "").strip()
        container = str(row.get("container") or "").strip()
        if host and container:
            rows.append({"host": host, "container": container})
    return sorted(rows, key=lambda item: len(item["host"]), reverse=True)


def _map_configured_path(text: str) -> Path | None:
    if not text:
        return None
    normalized_text = _normalize_mapping_key(text)
    for row in _path_mappings():
        host_key = _normalize_mapping_key(row["host"])
        if normalized_text == host_key:
            return Path(row["container"])
        if normalized_text.startswith(host_key + "/"):
            relative = normalized_text[len(host_key) + 1 :]
            return Path(row["container"]) / relative
    return None


def _join_host_path(host_root: str, relative: str) -> str:
    root = host_root.rstrip("\\/")
    separator = "\\" if _WINDOWS_DRIVE_RE.match(host_root) or "\\" in host_root else "/"
    return root + separator + relative.replace("/", separator)


def _example_settings_payload() -> dict[str, Any] | None:
    path = settings_example_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _default_settings_payload() -> dict[str, Any]:
    example = _example_settings_payload()
    if isinstance(example, dict):
        return dict(example)
    return {
        "schemaVersion": 1,
        "inputRoots": default_input_roots(),
        "outputRoot": default_output_root(),
        _TOKEN_KEY: "",
        "computeMode": "cpu",
        "runtime": default_runtime_settings(),
    }


def normalize_instance_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("local-"):
        text = text[len("local-") :]
    text = _INSTANCE_NAME_RE.sub("-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def generate_instance_name() -> str:
    return uuid4().hex[:10]


def settings_token(payload: dict[str, Any]) -> str:
    return str(payload.get(_TOKEN_KEY) or payload.get(_LEGACY_TOKEN_KEY) or "").strip()


def _normalize_api_port(value: Any, *, fallback: int = _DEFAULT_API_PORT) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return fallback
    if port < 1 or port > 65535:
        return fallback
    return port


def default_runtime_settings() -> dict[str, Any]:
    return {
        "instanceName": "",
        "apiPort": _DEFAULT_API_PORT,
    }


def normalize_runtime_settings(value: Any) -> dict[str, Any]:
    runtime = value if isinstance(value, dict) else {}
    instance_name = normalize_instance_name(runtime.get("instanceName"))
    api_port = _normalize_api_port(runtime.get("apiPort"))
    return {
        "instanceName": instance_name,
        "apiPort": api_port,
    }


def _normalize_input_root_rows(rows: Any, *, fallback: list[str]) -> list[str]:
    normalized: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, str):
                continue
            root_path = row.strip()
            if not root_path:
                continue
            if root_path not in normalized:
                normalized.append(root_path)
    return normalized or fallback


def _normalize_output_root(value: Any, *, fallback: str) -> str:
    root_path = value.strip() if isinstance(value, str) else ""
    if root_path:
        return root_path
    return fallback


def default_input_roots() -> list[str]:
    defaults = load_runtime_defaults()
    return _normalize_input_root_rows(
        defaults.get("inputRoots", []),
        fallback=[str(uploads_root())],
    )


def default_output_root() -> str:
    defaults = load_runtime_defaults()
    return _normalize_output_root(
        defaults.get("outputRoot"),
        fallback=str(outputs_root()),
    )


def supported_audio_extensions() -> list[str]:
    defaults = load_runtime_defaults()
    rows = defaults.get("audioExtensions", _DEFAULT_AUDIO_EXTENSIONS)
    if not isinstance(rows, list):
        return list(_DEFAULT_AUDIO_EXTENSIONS)
    normalized: list[str] = []
    for row in rows:
        value = str(row or "").strip().lower()
        if not value:
            continue
        if not value.startswith("."):
            value = f".{value}"
        if value not in normalized:
            normalized.append(value)
    return normalized or list(_DEFAULT_AUDIO_EXTENSIONS)


def load_settings() -> dict[str, Any]:
    if settings_path().exists():
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    else:
        payload = _default_settings_payload()
    schema_version = payload.get("schemaVersion", 1)
    if not isinstance(schema_version, int):
        schema_version = 1
    input_roots = _normalize_input_root_rows(
        payload.get("inputRoots", default_input_roots()),
        fallback=[] if "inputRoots" in payload else default_input_roots(),
    )
    output_root = _normalize_output_root(
        payload.get("outputRoot", default_output_root()),
        fallback="" if "outputRoot" in payload else default_output_root(),
    )
    compute_mode = str(payload.get("computeMode") or "cpu").strip().lower()
    if compute_mode not in {"cpu", "gpu"}:
        compute_mode = "cpu"
    return {
        "schemaVersion": schema_version,
        "runtime": normalize_runtime_settings(payload.get("runtime")),
        "inputRoots": input_roots,
        "outputRoot": output_root,
        _TOKEN_KEY: settings_token(payload),
        "computeMode": compute_mode,
    }


def ensure_runtime_settings() -> dict[str, Any]:
    settings = load_settings()
    runtime = normalize_runtime_settings(settings.get("runtime"))
    if not runtime["instanceName"]:
        runtime["instanceName"] = generate_instance_name()
    settings["runtime"] = runtime
    save_settings(settings)
    return runtime


def load_huggingface_token() -> str | None:
    value = settings_token(load_settings())
    return value or None


def save_settings(payload: dict[str, Any]) -> None:
    schema_version = payload.get("schemaVersion", 1)
    if not isinstance(schema_version, int):
        schema_version = 1
    input_roots = _normalize_input_root_rows(
        payload.get("inputRoots", []),
        fallback=[],
    )
    output_root = _normalize_output_root(
        payload.get("outputRoot"),
        fallback="",
    )
    compute_mode = str(payload.get("computeMode") or "cpu").strip().lower()
    if compute_mode not in {"cpu", "gpu"}:
        compute_mode = "cpu"
    runtime = normalize_runtime_settings(payload.get("runtime"))
    cleaned = {
        "schemaVersion": schema_version,
        "runtime": runtime,
        "inputRoots": input_roots,
        "outputRoot": output_root,
        _TOKEN_KEY: settings_token(payload),
        "computeMode": compute_mode,
    }
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def init_settings() -> dict[str, Any]:
    path = settings_path()
    if path.exists():
        return {
            "created": False,
            "path": str(path),
        }
    payload = load_settings()
    save_settings(payload)
    return {
        "created": True,
        "path": str(path),
    }


def save_huggingface_token(token: str | None) -> None:
    settings = load_settings()
    settings[_TOKEN_KEY] = token.strip() if token and token.strip() else ""
    save_settings(settings)


def save_worker_capabilities(payload: dict[str, Any]) -> None:
    path = worker_capabilities_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_worker_heartbeat(payload: dict[str, Any]) -> None:
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

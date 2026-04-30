from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

_WINDOWS_DRIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")
_PATH_MAPPINGS_ENV = "TIMELINE_FOR_AUDIO_PATH_MAPPINGS"


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
    return Path(os.getenv("TIMELINE_FOR_AUDIO_UPLOADS_ROOT", "/shared/uploads"))


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
        "audioExtensions": load_runtime_defaults().get(
            "audioExtensions", [".mp3", ".wav", ".m4a", ".aac", ".flac"]
        ),
        "huggingfaceToken": "",
        "computeMode": "cpu",
    }


def _normalize_input_root_rows(rows: Any, *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            root_path = str(row.get("path") or "").strip()
            if not root_path:
                continue
            root_id = str(row.get("id") or row.get("name") or f"root-{index}").strip()
            normalized.append(
                {
                    "id": root_id,
                    "path": root_path,
                }
            )
    return normalized or fallback


def _normalize_output_root(value: Any, *, fallback: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, list):
        value = next((row for row in value if isinstance(row, dict) and row.get("path")), None)
    if isinstance(value, dict):
        root_path = str(value.get("path") or "").strip()
        if root_path:
            return {"path": root_path}
    return fallback


def default_input_roots() -> list[dict[str, Any]]:
    defaults = load_runtime_defaults()
    return _normalize_input_root_rows(
        defaults.get("inputRoots", []),
        fallback=[
            {
                "id": "uploads",
                "path": str(uploads_root()),
            }
        ],
    )


def default_output_root() -> dict[str, Any]:
    defaults = load_runtime_defaults()
    return _normalize_output_root(
        defaults.get("outputRoot"),
        fallback={
            "path": str(outputs_root()),
        },
    )


def load_settings() -> dict[str, Any]:
    if settings_path().exists():
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    else:
        payload = _default_settings_payload()
    if "audioExtensions" not in payload:
        payload["audioExtensions"] = payload.get("videoExtensions", [])
    payload["inputRoots"] = _normalize_input_root_rows(
        payload.get("inputRoots", default_input_roots()),
        fallback=[] if "inputRoots" in payload else default_input_roots(),
    )
    payload["outputRoot"] = _normalize_output_root(
        payload.get("outputRoot", default_output_root()),
        fallback={} if "outputRoot" in payload else default_output_root(),
    )
    payload["computeMode"] = str(payload.get("computeMode") or "cpu").strip().lower()
    if payload["computeMode"] not in {"cpu", "gpu"}:
        payload["computeMode"] = "cpu"
    payload.pop("processingQuality", None)
    payload.pop("secondPassEnabled", None)
    payload.pop("contextBuilderVersion", None)
    payload.pop("ipaBackend", None)
    payload.pop("uiLanguage", None)
    payload.pop("refreshBatchSize", None)
    payload["huggingfaceToken"] = str(payload.get("huggingfaceToken") or "").strip()
    return payload


def load_huggingface_token() -> str | None:
    value = str(load_settings().get("huggingfaceToken") or "").strip()
    return value or None


def save_settings(payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["inputRoots"] = _normalize_input_root_rows(
        payload.get("inputRoots", []),
        fallback=[],
    )
    payload["outputRoot"] = _normalize_output_root(
        payload.get("outputRoot"),
        fallback={},
    )
    payload.pop("processingQuality", None)
    payload.pop("secondPassEnabled", None)
    payload["huggingfaceToken"] = str(payload.get("huggingfaceToken") or "").strip()
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    settings["huggingfaceToken"] = token.strip() if token and token.strip() else ""
    save_settings(settings)


def save_worker_capabilities(payload: dict[str, Any]) -> None:
    path = worker_capabilities_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_worker_heartbeat(payload: dict[str, Any]) -> None:
    path = worker_heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

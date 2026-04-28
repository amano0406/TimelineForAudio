from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from .signature import CONTEXT_BUILDER_VERSION
from .ipa_backend import resolve_ipa_backend
from .vad_profile import resolve_vad_profile

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


def token_path() -> Path:
    return appdata_root() / "secrets" / "huggingface.token"


def worker_capabilities_path() -> Path:
    return appdata_root() / "worker-capabilities.json"


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
        "outputRoots": default_output_roots(),
        "audioExtensions": load_runtime_defaults().get(
            "audioExtensions", [".mp3", ".wav", ".m4a", ".aac", ".flac"]
        ),
        "huggingfaceTermsConfirmed": False,
        "computeMode": "cpu",
        "contextBuilderVersion": CONTEXT_BUILDER_VERSION,
        "ipaBackend": resolve_ipa_backend(None),
        "vadProfile": resolve_vad_profile(None),
        "uiLanguage": "en",
    }


def _normalize_root_rows(rows: Any, *, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            root_path = str(row.get("path") or "").strip()
            if not root_path:
                continue
            root_id = str(row.get("id") or row.get("name") or f"root-{index}").strip()
            display_name = str(row.get("displayName") or row.get("name") or root_id).strip()
            normalized.append(
                {
                    "id": root_id,
                    "displayName": display_name or root_id,
                    "path": root_path,
                    "enabled": bool(row.get("enabled", True)),
                }
            )
    return normalized or fallback


def default_input_roots() -> list[dict[str, Any]]:
    defaults = load_runtime_defaults()
    return _normalize_root_rows(
        defaults.get("inputRoots", []),
        fallback=[
            {
                "id": "uploads",
                "displayName": "Uploads",
                "path": str(uploads_root()),
                "enabled": True,
            }
        ],
    )


def default_output_roots() -> list[dict[str, Any]]:
    defaults = load_runtime_defaults()
    return _normalize_root_rows(
        defaults.get("outputRoots", []),
        fallback=[
            {
                "id": "runs",
                "displayName": "Runs",
                "path": str(outputs_root()),
                "enabled": True,
            }
        ],
    )


def load_settings() -> dict[str, Any]:
    if settings_path().exists():
        payload = json.loads(settings_path().read_text(encoding="utf-8"))
    else:
        payload = _default_settings_payload()
    if "audioExtensions" not in payload:
        payload["audioExtensions"] = payload.get("videoExtensions", [])
    payload["inputRoots"] = _normalize_root_rows(
        payload.get("inputRoots", default_input_roots()),
        fallback=[] if "inputRoots" in payload else default_input_roots(),
    )
    payload["outputRoots"] = _normalize_root_rows(
        payload.get("outputRoots", default_output_roots()),
        fallback=[] if "outputRoots" in payload else default_output_roots(),
    )
    payload["computeMode"] = str(payload.get("computeMode") or "cpu").strip().lower()
    if payload["computeMode"] not in {"cpu", "gpu"}:
        payload["computeMode"] = "cpu"
    payload.pop("processingQuality", None)
    payload.pop("secondPassEnabled", None)
    payload["contextBuilderVersion"] = (
        str(payload.get("contextBuilderVersion") or CONTEXT_BUILDER_VERSION).strip()
        or CONTEXT_BUILDER_VERSION
    )
    payload["ipaBackend"] = resolve_ipa_backend(str(payload.get("ipaBackend") or ""))
    payload["vadProfile"] = resolve_vad_profile(str(payload.get("vadProfile") or ""))
    payload["uiLanguage"] = str(payload.get("uiLanguage") or "en").strip() or "en"
    return payload


def load_huggingface_token() -> str | None:
    path = token_path()
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8", errors="replace").strip()
    return value or None


def save_settings(payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload.pop("processingQuality", None)
    payload.pop("secondPassEnabled", None)
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def init_settings() -> dict[str, Any]:
    path = settings_path()
    if path.exists():
        return {
            "created": False,
            "settings_path": str(path),
            "message": "settings.json already exists.",
        }
    payload = load_settings()
    save_settings(payload)
    return {
        "created": True,
        "settings_path": str(path),
        "message": "settings.json was created.",
    }


def save_huggingface_token(token: str | None) -> None:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if token and token.strip():
        path.write_text(token.strip(), encoding="utf-8")
        return
    if path.exists():
        path.unlink()


def save_worker_capabilities(payload: dict[str, Any]) -> None:
    path = worker_capabilities_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

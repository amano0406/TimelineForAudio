from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from .fs_utils import ensure_dir
from .settings import appdata_root

_FINAL_TIMELINE_FILE = "timeline.json"
_CONVERSION_INFO_FILE = "convert_info.json"


def catalog_path(output_root: Path) -> Path:
    return appdata_root() / "catalog" / f"{_output_root_key(output_root)}.jsonl"


def normalize_file_identity(value: str | None) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rstrip("/")
    return normalized.lower()


def catalog_key(
    source_hash: str,
    conversion_signature: str,
    source_file_identity: str | None = None,
) -> str:
    identity = normalize_file_identity(source_file_identity)
    hash_part = source_hash.strip().lower()
    signature_part = conversion_signature.strip().lower()
    if identity:
        return f"{identity}::{hash_part}::{signature_part}"
    return f"{hash_part}::{signature_part}"


def load_catalog(output_root: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in load_catalog_rows(output_root):
        file_hash = str(row.get("source_hash") or row.get("sha256") or "")
        conversion_signature = str(row.get("conversion_signature") or "")
        if file_hash and conversion_signature:
            rows[catalog_key(file_hash, conversion_signature, row.get("source_file_identity"))] = row
    return rows


def load_catalog_rows(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for row in _master_artifact_rows(output_root):
        artifact_path = str(row.get("artifact_path") or "")
        if artifact_path:
            seen_artifacts.add(_normalize_path_for_dedupe(artifact_path))
        rows.append(row)

    cache_path = catalog_path(output_root)
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            artifact_path = str(row.get("artifact_path") or "")
            if not artifact_path or not Path(artifact_path).exists():
                continue
            dedupe_key = _normalize_path_for_dedupe(artifact_path)
            if dedupe_key in seen_artifacts:
                continue
            seen_artifacts.add(dedupe_key)
            rows.append(row)
    return rows


def append_catalog_rows(output_root: Path, rows: list[dict[str, Any]]) -> None:
    path = catalog_path(output_root)
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _master_artifact_rows(output_root: Path) -> list[dict[str, Any]]:
    if not output_root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item_dir in sorted(output_root.iterdir(), key=lambda item: item.name.lower()):
        if not item_dir.is_dir() or item_dir.name.startswith("."):
            continue
        timeline_path = item_dir / _FINAL_TIMELINE_FILE
        conversion_path = item_dir / _CONVERSION_INFO_FILE
        if not timeline_path.exists() or not conversion_path.exists():
            continue
        row = _row_from_master_item_dir(
            item_id=item_dir.name,
            item_dir=item_dir,
            timeline_path=timeline_path,
            conversion_path=conversion_path,
        )
        if row is not None:
            rows.append(row)
    return rows


def _row_from_master_item_dir(
    *,
    item_id: str,
    item_dir: Path,
    timeline_path: Path,
    conversion_path: Path,
) -> dict[str, Any] | None:
    conversion = _read_json(conversion_path)
    timeline = _read_json(timeline_path)
    source = _first_dict(conversion.get("source"), timeline.get("source"))
    pipeline = _first_dict(conversion.get("pipeline"), timeline.get("pipeline"))
    if not source and not pipeline:
        return None
    return {
        "audio_id": item_id,
        "media_id": item_id,
        "item_dir": str(item_dir),
        "artifact_path": str(timeline_path),
        "conversion_info_path": str(conversion_path),
        "source_hash": source.get("source_hash"),
        "conversion_signature": pipeline.get("generation_signature"),
        "source_id": source.get("source_id"),
        "source_relative_path": source.get("source_relative_path"),
        "source_file_identity": source.get("source_file_identity"),
        "file_name": source.get("file_name"),
        "original_path": source.get("original_path"),
        "duration_seconds": source.get("duration_sec"),
        "created_at": conversion.get("generated_at"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _normalize_path_for_dedupe(value: str) -> str:
    try:
        return str(Path(value).resolve(strict=False)).lower()
    except Exception:
        return str(value).strip().lower()


def _output_root_key(output_root: Path) -> str:
    try:
        normalized = str(output_root.resolve(strict=False))
    except Exception:
        normalized = str(output_root)
    return hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()[:16]

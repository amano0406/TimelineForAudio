from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .fs_utils import ensure_dir


def catalog_path(output_root: Path) -> Path:
    return output_root / ".timeline-for-audio" / "catalog.jsonl"


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
    path = catalog_path(output_root)
    if not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        file_hash = str(row.get("source_hash") or row.get("sha256") or "")
        conversion_signature = str(row.get("conversion_signature") or "")
        if file_hash and conversion_signature:
            rows[catalog_key(file_hash, conversion_signature, row.get("source_file_identity"))] = row
    return rows


def append_catalog_rows(output_root: Path, rows: list[dict[str, Any]]) -> None:
    path = catalog_path(output_root)
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

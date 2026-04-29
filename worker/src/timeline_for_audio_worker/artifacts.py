from __future__ import annotations

from pathlib import Path
from typing import Any

from .fs_utils import write_json_atomic


def write_media_artifacts_index(
    *,
    media_dir: Path,
    media_id: str,
    primary_artifact_kind: str,
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "media_id": media_id,
        "primary_artifact_kind": primary_artifact_kind,
        "artifacts": artifacts,
    }
    write_json_atomic(media_dir / "artifacts.json", payload)
    return payload

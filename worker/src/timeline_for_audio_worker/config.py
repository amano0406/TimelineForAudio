from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class SourceDirectory:
    name: str
    path: str
    recursive: bool = True


@dataclass
class ChangeDetectionConfig:
    phash_same_threshold: int = 4
    dhash_same_threshold: int = 6
    mean_diff_same_threshold: float = 0.015
    changed_ratio_same_threshold: float = 0.01
    phash_minor_threshold: int = 12
    dhash_minor_threshold: int = 14
    mean_diff_minor_threshold: float = 0.05
    changed_ratio_minor_threshold: float = 0.05


@dataclass
class AppConfig:
    project_name: str
    source_directories: list[SourceDirectory]
    output_root: str
    audio_extensions: list[str]
    change_detection: ChangeDetectionConfig

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: Path) -> AppConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig(
        project_name=payload["project_name"],
        source_directories=[SourceDirectory(**row) for row in payload["source_directories"]],
        output_root=payload["output_root"],
        audio_extensions=payload["audio_extensions"],
        change_detection=ChangeDetectionConfig(**payload["change_detection"]),
    )

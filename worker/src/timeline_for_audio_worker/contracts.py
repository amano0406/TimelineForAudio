from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

from .vad_profile import resolve_vad_profile


@dataclass
class InputItem:
    input_id: str
    source_kind: str
    source_id: str
    original_path: str
    display_name: str
    size_bytes: int = 0
    uploaded_path: str | None = None
    source_relative_path: str | None = None
    source_file_identity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunRequest:
    schema_version: int
    run_id: str
    created_at: str
    output_root_id: str
    output_root_path: str
    profile: str
    compute_mode: str
    pipeline_version: str
    conversion_signature: str
    acoustic_unit_backend: str
    acoustic_unit_model_id: str
    diarization_enabled: bool
    diarization_model_id: str | None
    vad_backend: str
    vad_model_id: str
    reprocess_duplicates: bool
    token_enabled: bool
    input_items: list[InputItem]
    vad_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "output_root_id": self.output_root_id,
            "output_root_path": self.output_root_path,
            "profile": self.profile,
            "compute_mode": self.compute_mode,
            "pipeline_version": self.pipeline_version,
            "generation_signature": self.conversion_signature,
            "conversion_signature": self.conversion_signature,
            "acoustic_unit_backend": self.acoustic_unit_backend,
            "acoustic_unit_model_id": self.acoustic_unit_model_id,
            "diarization_enabled": self.diarization_enabled,
            "diarization_model_id": self.diarization_model_id,
            "vad_backend": self.vad_backend,
            "vad_model_id": self.vad_model_id,
            "reprocess_duplicates": self.reprocess_duplicates,
            "token_enabled": self.token_enabled,
            "vad_profile": resolve_vad_profile(self.vad_profile),
            "input_items": [item.to_dict() for item in self.input_items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunRequest":
        return cls(
            schema_version=int(payload["schema_version"]),
            run_id=str(payload["run_id"]),
            created_at=str(payload["created_at"]),
            output_root_id=str(payload["output_root_id"]),
            output_root_path=str(payload["output_root_path"]),
            profile=str(payload["profile"]),
            compute_mode=str(payload.get("compute_mode") or "cpu"),
            pipeline_version=str(payload.get("pipeline_version") or ""),
            conversion_signature=str(
                payload.get("generation_signature") or payload.get("conversion_signature") or ""
            ),
            acoustic_unit_backend=str(payload.get("acoustic_unit_backend") or ""),
            acoustic_unit_model_id=str(payload.get("acoustic_unit_model_id") or ""),
            diarization_enabled=bool(payload.get("diarization_enabled", False)),
            diarization_model_id=(
                str(payload["diarization_model_id"])
                if payload.get("diarization_model_id") not in (None, "")
                else None
            ),
            vad_backend=str(payload.get("vad_backend") or ""),
            vad_model_id=str(payload.get("vad_model_id") or ""),
            reprocess_duplicates=bool(payload["reprocess_duplicates"]),
            token_enabled=bool(payload.get("token_enabled", False)),
            input_items=[InputItem(**item) for item in payload.get("input_items", [])],
            vad_profile=resolve_vad_profile(str(payload.get("vad_profile") or "")),
        )

    @property
    def generation_signature(self) -> str:
        return self.conversion_signature

    @generation_signature.setter
    def generation_signature(self, value: str) -> None:
        self.conversion_signature = value


@dataclass
class RunStatus:
    schema_version: int = 1
    run_id: str = ""
    state: str = "pending"
    current_stage: str = "queued"
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    items_total: int = 0
    items_done: int = 0
    items_skipped: int = 0
    items_failed: int = 0
    current_item: str | None = None
    current_item_elapsed_sec: float = 0.0
    current_stage_elapsed_sec: float = 0.0
    processed_duration_sec: float = 0.0
    total_duration_sec: float = 0.0
    estimated_remaining_sec: float | None = None
    progress_percent: float = 0.0
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunStatus":
        payload = dict(payload)
        legacy_key_map = {
            "videos_total": "items_total",
            "videos_done": "items_done",
            "videos_skipped": "items_skipped",
            "videos_failed": "items_failed",
            "current_media": "current_item",
            "current_media_elapsed_sec": "current_item_elapsed_sec",
        }
        for old_key, new_key in legacy_key_map.items():
            if new_key not in payload and old_key in payload:
                payload[new_key] = payload[old_key]
        payload["run_id"] = str(payload.get("run_id") or "")
        allowed_keys = {field_info.name for field_info in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in allowed_keys})

    @property
    def videos_total(self) -> int:
        return self.items_total

    @videos_total.setter
    def videos_total(self, value: int) -> None:
        self.items_total = value

    @property
    def videos_done(self) -> int:
        return self.items_done

    @videos_done.setter
    def videos_done(self, value: int) -> None:
        self.items_done = value

    @property
    def videos_skipped(self) -> int:
        return self.items_skipped

    @videos_skipped.setter
    def videos_skipped(self, value: int) -> None:
        self.items_skipped = value

    @property
    def videos_failed(self) -> int:
        return self.items_failed

    @videos_failed.setter
    def videos_failed(self, value: int) -> None:
        self.items_failed = value

    @property
    def current_media(self) -> str | None:
        return self.current_item

    @current_media.setter
    def current_media(self, value: str | None) -> None:
        self.current_item = value

    @property
    def current_media_elapsed_sec(self) -> float:
        return self.current_item_elapsed_sec

    @current_media_elapsed_sec.setter
    def current_media_elapsed_sec(self, value: float) -> None:
        self.current_item_elapsed_sec = value


@dataclass
class RunResult:
    schema_version: int = 1
    run_id: str = ""
    state: str = "pending"
    run_dir: str = ""
    output_root_id: str = ""
    output_root_path: str = ""
    processed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    batch_count: int = 0
    timeline_index_path: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunResult":
        payload = dict(payload)
        payload["run_id"] = str(payload.get("run_id") or "")
        allowed_keys = {field_info.name for field_info in fields(cls)}
        return cls(**{key: value for key, value in payload.items() if key in allowed_keys})


@dataclass
class ManifestItem:
    input_id: str
    source_kind: str
    original_path: str
    file_name: str
    size_bytes: int
    duration_seconds: float
    source_hash: str
    conversion_signature: str
    duplicate_status: str
    duplicate_of: str | None = None
    audio_id: str | None = None
    status: str = "pending"
    container_name: str | None = None
    extension: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    audio_sample_rate: int | None = None
    bitrate: int | None = None
    diarization_enabled: bool = False
    speaker_count: int | None = None
    speaker_count_status: str | None = None
    speaker_count_note: str | None = None
    model_id: str | None = None
    model_version: str | None = None
    pipeline_version: str | None = None
    captured_at: str | None = None
    processing_wall_seconds: float | None = None
    stage_elapsed_seconds: dict[str, float] = field(default_factory=dict)
    pause_summary: dict[str, Any] = field(default_factory=dict)
    loudness_summary: dict[str, Any] = field(default_factory=dict)
    speaking_rate_summary: dict[str, Any] = field(default_factory=dict)
    pitch_summary: dict[str, Any] = field(default_factory=dict)
    speaker_confidence_summary: dict[str, Any] = field(default_factory=dict)
    diarization_quality_summary: dict[str, Any] = field(default_factory=dict)
    optional_voice_feature_summary: dict[str, Any] = field(default_factory=dict)
    source_id: str | None = None
    source_relative_path: str | None = None
    source_file_identity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["generation_signature"] = self.conversion_signature
        return payload

    @property
    def sha256(self) -> str:
        return self.source_hash

    @sha256.setter
    def sha256(self, value: str) -> None:
        self.source_hash = value

    @property
    def generation_signature(self) -> str:
        return self.conversion_signature

    @generation_signature.setter
    def generation_signature(self, value: str) -> None:
        self.conversion_signature = value

    @property
    def media_id(self) -> str | None:
        return self.audio_id

    @media_id.setter
    def media_id(self, value: str | None) -> None:
        self.audio_id = value

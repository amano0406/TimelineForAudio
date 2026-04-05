from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InputItem:
    input_id: str
    source_kind: str
    source_id: str
    original_path: str
    display_name: str
    size_bytes: int = 0
    uploaded_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobRequest:
    schema_version: int
    job_id: str
    created_at: str
    output_root_id: str
    output_root_path: str
    profile: str
    compute_mode: str
    processing_quality: str
    pipeline_version: str
    conversion_signature: str
    transcription_backend: str
    transcription_model_id: str
    transcription_initial_prompt: str | None
    transcript_normalization_mode: str
    transcript_normalization_glossary: str | None
    diarization_enabled: bool
    diarization_model_id: str | None
    vad_backend: str
    vad_model_id: str
    reprocess_duplicates: bool
    token_enabled: bool
    input_items: list[InputItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "output_root_id": self.output_root_id,
            "output_root_path": self.output_root_path,
            "profile": self.profile,
            "compute_mode": self.compute_mode,
            "processing_quality": self.processing_quality,
            "pipeline_version": self.pipeline_version,
            "conversion_signature": self.conversion_signature,
            "transcription_backend": self.transcription_backend,
            "transcription_model_id": self.transcription_model_id,
            "transcription_initial_prompt": self.transcription_initial_prompt,
            "transcript_normalization_mode": self.transcript_normalization_mode,
            "transcript_normalization_glossary": self.transcript_normalization_glossary,
            "diarization_enabled": self.diarization_enabled,
            "diarization_model_id": self.diarization_model_id,
            "vad_backend": self.vad_backend,
            "vad_model_id": self.vad_model_id,
            "reprocess_duplicates": self.reprocess_duplicates,
            "token_enabled": self.token_enabled,
            "input_items": [item.to_dict() for item in self.input_items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "JobRequest":
        return cls(
            schema_version=int(payload["schema_version"]),
            job_id=str(payload["job_id"]),
            created_at=str(payload["created_at"]),
            output_root_id=str(payload["output_root_id"]),
            output_root_path=str(payload["output_root_path"]),
            profile=str(payload["profile"]),
            compute_mode=str(payload.get("compute_mode") or "cpu"),
            processing_quality=str(payload.get("processing_quality") or "standard"),
            pipeline_version=str(payload.get("pipeline_version") or ""),
            conversion_signature=str(payload.get("conversion_signature") or ""),
            transcription_backend=str(payload.get("transcription_backend") or ""),
            transcription_model_id=str(payload.get("transcription_model_id") or ""),
            transcription_initial_prompt=(
                str(payload["transcription_initial_prompt"])
                if payload.get("transcription_initial_prompt") not in (None, "")
                else None
            ),
            transcript_normalization_mode=str(
                payload.get("transcript_normalization_mode") or "deterministic"
            ),
            transcript_normalization_glossary=(
                str(payload["transcript_normalization_glossary"])
                if payload.get("transcript_normalization_glossary") not in (None, "")
                else None
            ),
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
        )


@dataclass
class JobStatus:
    schema_version: int = 1
    job_id: str = ""
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
class JobResult:
    schema_version: int = 1
    job_id: str = ""
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def sha256(self) -> str:
        return self.source_hash

    @sha256.setter
    def sha256(self, value: str) -> None:
        self.source_hash = value

    @property
    def media_id(self) -> str | None:
        return self.audio_id

    @media_id.setter
    def media_id(self, value: str | None) -> None:
        self.audio_id = value

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .fs_utils import now_iso
from .signature import (
    DIARIZATION_MODEL_ID,
    PIPELINE_VERSION,
    TRANSCRIPTION_BACKEND_NAME,
    VAD_BACKEND,
    VAD_MODEL_ID,
    build_generation_signature,
    normalize_compute_mode,
    resolve_transcription_model_id,
)
from .settings import load_huggingface_token
from .vad_profile import resolve_vad_profile

HUGGING_FACE_MODEL_URL = "https://huggingface.co/{model_id}"
HUGGING_FACE_MODEL_API_URL = "https://huggingface.co/api/models/{model_id}"


@dataclass(frozen=True)
class ModelInventoryRow:
    role: str
    display_name: str
    source: str
    model_id: str
    backend: str
    required: bool
    configured: bool
    requires_huggingface_token: bool
    requires_access_approval: bool
    unit_type: str | None = None
    url: str | None = None
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_inventory(
    *,
    settings: dict[str, Any],
    include_remote: bool = False,
) -> dict[str, Any]:
    compute_mode = normalize_compute_mode(settings.get("computeMode"))
    vad_profile = resolve_vad_profile(str(settings.get("vadProfile") or ""))
    rows = _configured_model_rows(settings=settings)
    model_rows = [row.to_dict() for row in rows]
    if include_remote:
        token = load_huggingface_token()
        for row in model_rows:
            if row.get("source") != "huggingface":
                continue
            row["huggingface"] = fetch_huggingface_model_metadata(
                str(row.get("model_id") or ""),
                token=token,
            )
    return {
        "schema_version": 1,
        "generated_at": now_iso(),
        "pipeline": {
            "name": "TimelineForAudio",
            "pipeline_version": PIPELINE_VERSION,
            "compute_mode": compute_mode,
            "generation_signature": build_generation_signature(
                compute_mode=compute_mode,
                diarization_enabled=True,
                vad_profile=vad_profile,
            ),
        },
        "models": model_rows,
    }


def _configured_model_rows(*, settings: dict[str, Any]) -> list[ModelInventoryRow]:
    del settings
    return [
        ModelInventoryRow(
            role="speaker_diarization",
            display_name="Speaker diarization",
            source="huggingface",
            model_id=DIARIZATION_MODEL_ID,
            backend="pyannote.audio",
            required=True,
            configured=True,
            requires_huggingface_token=True,
            requires_access_approval=True,
            url=HUGGING_FACE_MODEL_URL.format(model_id=DIARIZATION_MODEL_ID),
            notes=[
                "Used to assign mechanical speaker labels such as SPEAKER_00.",
                "Access approval on Hugging Face is required before processing.",
            ],
        ),
        ModelInventoryRow(
            role="speech_transcription",
            display_name="Speech transcription",
            source="huggingface",
            model_id=resolve_transcription_model_id(),
            backend=TRANSCRIPTION_BACKEND_NAME,
            required=True,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            url=HUGGING_FACE_MODEL_URL.format(model_id=resolve_transcription_model_id()),
            notes=[
                "Used to transcribe source audio with automatic language detection.",
                "TimelineForAudio stores Whisper text as-is and only adds speaker labels by timestamp overlap.",
            ],
        ),
        ModelInventoryRow(
            role="speech_candidate_detection",
            display_name="Speech candidate detection",
            source="local_tool",
            model_id=VAD_MODEL_ID,
            backend=VAD_BACKEND,
            required=True,
            configured=True,
            requires_huggingface_token=False,
            requires_access_approval=False,
            notes=[
                "This is an ffmpeg silencedetect configuration, not a Hugging Face model.",
            ],
        ),
    ]


def fetch_huggingface_model_metadata(
    model_id: str,
    *,
    token: str | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    if not model_id:
        return {
            "remote_status": "skipped",
            "error": "model_id is empty.",
        }
    request = urllib.request.Request(
        HUGGING_FACE_MODEL_API_URL.format(model_id=model_id),
        headers=_huggingface_headers(token),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "remote_status": "error",
            "http_status": exc.code,
            "error": f"Hugging Face returned HTTP {exc.code}.",
        }
    except Exception as exc:
        return {
            "remote_status": "error",
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "remote_status": "error",
            "error": "Hugging Face response was not a JSON object.",
        }
    return _summarize_huggingface_model_payload(payload)


def _huggingface_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "TimelineForAudio/1.0",
    }
    value = str(token or "").strip()
    if value:
        headers["Authorization"] = f"Bearer {value}"
    return headers


def _summarize_huggingface_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    card_data = payload.get("cardData") if isinstance(payload.get("cardData"), dict) else {}
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    license_value = card_data.get("license") or _license_from_tags(tags)
    return {
        "remote_status": "ok",
        "id": payload.get("id"),
        "sha": payload.get("sha"),
        "last_modified": payload.get("lastModified"),
        "private": payload.get("private"),
        "gated": payload.get("gated"),
        "disabled": payload.get("disabled"),
        "pipeline_tag": payload.get("pipeline_tag"),
        "library_name": payload.get("library_name") or card_data.get("library_name"),
        "license": license_value,
        "license_source": "cardData.license" if card_data.get("license") else "tags",
        "tags": tags,
        "downloads": payload.get("downloads"),
        "likes": payload.get("likes"),
        "model_card_url": HUGGING_FACE_MODEL_URL.format(model_id=str(payload.get("id") or "")),
    }


def _license_from_tags(tags: list[Any]) -> str | None:
    for tag in tags:
        text = str(tag or "")
        if text.startswith("license:"):
            return text.split(":", 1)[1] or None
    return None

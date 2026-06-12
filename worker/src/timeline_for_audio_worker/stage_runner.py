from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .diarization import generate_speaker_turns
from .transcription import generate_transcript_segments


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _transcription_payload(result: Any) -> dict[str, Any]:
    return {
        "backend_name": result.backend_name,
        "model_id": result.model_id,
        "status": result.status,
        "device": result.device,
        "compute_type": result.compute_type,
        "language": result.language,
        "language_probability": result.language_probability,
        "duration": result.duration,
        "warnings": list(result.warnings),
        "segments": [
            {
                "index": segment.index,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "avg_logprob": segment.avg_logprob,
                "no_speech_probability": segment.no_speech_probability,
            }
            for segment in result.segments
        ],
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        raise SystemExit(
            "usage: python -m timeline_for_audio_worker.stage_runner "
            "<diarize|transcribe> <request.json> <output.json>"
        )

    stage, request_path_text, output_path_text = args
    request_path = Path(request_path_text)
    output_path = Path(output_path_text)
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))

    if stage == "diarize":
        payload = generate_speaker_turns(
            source_name=str(request.get("source_name") or ""),
            audio_path=Path(str(request.get("audio_path") or "")),
            compute_mode=str(request.get("compute_mode") or ""),
        )
        _write_json(output_path, payload)
        return 0

    if stage == "transcribe":
        result = generate_transcript_segments(
            audio_path=Path(str(request.get("audio_path") or "")),
            compute_mode=str(request.get("compute_mode") or ""),
        )
        _write_json(output_path, _transcription_payload(result))
        return 0

    raise ValueError(f"Unknown stage: {stage}")


if __name__ == "__main__":
    raise SystemExit(main())

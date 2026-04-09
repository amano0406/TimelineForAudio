from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.contracts import ManifestItem
from timeline_for_audio_worker.eta import build_eta_predictor, estimate_remaining_seconds


def _write_run(
    root: Path,
    *,
    job_id: str,
    compute_mode: str,
    processing_quality: str,
    items: list[dict[str, object]],
) -> None:
    run_dir = root / job_id
    run_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "schema_version": 1,
        "job_id": job_id,
        "created_at": "2026-04-01T10:00:00+09:00",
        "output_root_id": "runs",
        "output_root_path": str(root),
        "profile": "quality-first",
        "compute_mode": compute_mode,
        "processing_quality": processing_quality,
        "reprocess_duplicates": False,
        "token_enabled": False,
        "input_items": [],
    }
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "generated_at": "2026-04-01T10:00:00+09:00",
        "items": items,
    }
    (run_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _manifest_item(
    *,
    input_id: str,
    file_name: str,
    size_bytes: int,
    duration_seconds: float,
    source_hash: str,
    audio_id: str,
    container_name: str,
    audio_codec: str,
    audio_channels: int,
    audio_sample_rate: int,
    bitrate: int,
    status: str = "queued",
) -> ManifestItem:
    return ManifestItem(
        input_id=input_id,
        source_kind="upload",
        original_path=file_name,
        file_name=file_name,
        size_bytes=size_bytes,
        duration_seconds=duration_seconds,
        source_hash=source_hash,
        conversion_signature="sig-123",
        duplicate_status="new",
        audio_id=audio_id,
        status=status,
        container_name=container_name,
        extension=Path(file_name).suffix.lower(),
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        audio_sample_rate=audio_sample_rate,
        bitrate=bitrate,
    )


class EtaPredictorTests(unittest.TestCase):
    def test_predictor_prefers_similar_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-mono",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 4.0,
                        "processing_wall_seconds": 20.0,
                        "container_name": "wav",
                        "audio_codec": "pcm_s16le",
                        "audio_channels": 1,
                        "audio_sample_rate": 16000,
                        "bitrate": 64000,
                    }
                ],
            )
            _write_run(
                root,
                job_id="job-old-stereo",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 4.0,
                        "processing_wall_seconds": 34.0,
                        "container_name": "m4a",
                        "audio_codec": "aac",
                        "audio_channels": 2,
                        "audio_sample_rate": 48000,
                        "bitrate": 192000,
                    }
                ],
            )

            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            mono_item = _manifest_item(
                input_id="input-1",
                file_name="voice-note.wav",
                size_bytes=600_000,
                duration_seconds=4.0,
                source_hash="a" * 64,
                audio_id="audio-1",
                container_name="wav",
                audio_codec="pcm_s16le",
                audio_channels=1,
                audio_sample_rate=16000,
                bitrate=64000,
            )
            stereo_item = _manifest_item(
                input_id="input-2",
                file_name="meeting.m4a",
                size_bytes=4_400_000,
                duration_seconds=4.0,
                source_hash="b" * 64,
                audio_id="audio-2",
                container_name="m4a",
                audio_codec="aac",
                audio_channels=2,
                audio_sample_rate=48000,
                bitrate=192000,
            )

            mono_prediction = predictor.predict_item(mono_item)
            stereo_prediction = predictor.predict_item(stereo_item)

            self.assertIsNotNone(mono_prediction)
            self.assertIsNotNone(stereo_prediction)
            assert mono_prediction is not None
            assert stereo_prediction is not None
            self.assertLess(mono_prediction.total_seconds, stereo_prediction.total_seconds)
            self.assertGreaterEqual(mono_prediction.sample_count, 2)

    def test_remaining_estimate_blends_history_with_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-1",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 5.0,
                        "processing_wall_seconds": 10.0,
                        "container_name": "wav",
                        "audio_codec": "pcm_s16le",
                        "audio_channels": 1,
                        "audio_sample_rate": 16000,
                        "bitrate": 64000,
                    }
                ],
            )
            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            items = [
                _manifest_item(
                    input_id="input-1",
                    file_name="clip-1.wav",
                    size_bytes=1_000,
                    duration_seconds=5.0,
                    source_hash="c" * 64,
                    audio_id="audio-1",
                    container_name="wav",
                    audio_codec="pcm_s16le",
                    audio_channels=1,
                    audio_sample_rate=16000,
                    bitrate=64000,
                ),
                _manifest_item(
                    input_id="input-2",
                    file_name="clip-2.wav",
                    size_bytes=2_000,
                    duration_seconds=5.0,
                    source_hash="d" * 64,
                    audio_id="audio-2",
                    container_name="wav",
                    audio_codec="pcm_s16le",
                    audio_channels=1,
                    audio_sample_rate=16000,
                    bitrate=64000,
                ),
            ]

            remaining = estimate_remaining_seconds(
                predictor=predictor,
                manifest_items=items,
                legacy_remaining_sec=40.0,
                current_item_index=0,
                current_item_elapsed_sec=3.0,
                include_export_stage=True,
            )

            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertGreater(remaining, 12.0)
            self.assertLess(remaining, 40.0)

    def test_remaining_estimate_respects_current_stage_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_run(
                root,
                job_id="job-old-stage-aware",
                compute_mode="cpu",
                processing_quality="standard",
                items=[
                    {
                        "status": "completed",
                        "duration_seconds": 5.0,
                        "processing_wall_seconds": 10.0,
                        "container_name": "wav",
                        "audio_codec": "pcm_s16le",
                        "audio_channels": 1,
                        "audio_sample_rate": 16000,
                        "bitrate": 64000,
                        "stage_elapsed_seconds": {
                            "extract_audio": 1.0,
                            "transcribe": 5.0,
                            "normalize_transcript": 1.0,
                            "analyze_audio": 2.0,
                            "timeline_render": 1.0,
                        },
                    }
                ],
            )
            predictor = build_eta_predictor(
                output_root=root,
                current_job_id="job-current",
                compute_mode="cpu",
                processing_quality="standard",
            )

            items = [
                _manifest_item(
                    input_id="input-1",
                    file_name="clip-1.wav",
                    size_bytes=1_000,
                    duration_seconds=5.0,
                    source_hash="e" * 64,
                    audio_id="audio-1",
                    container_name="wav",
                    audio_codec="pcm_s16le",
                    audio_channels=1,
                    audio_sample_rate=16000,
                    bitrate=64000,
                )
            ]

            remaining = estimate_remaining_seconds(
                predictor=predictor,
                manifest_items=items,
                legacy_remaining_sec=None,
                current_item_index=0,
                current_item_elapsed_sec=6.0,
                current_stage_name="transcribe",
                current_stage_elapsed_sec=1.0,
                include_export_stage=False,
            )

            self.assertIsNotNone(remaining)
            assert remaining is not None
            self.assertAlmostEqual(remaining, 8.0, places=3)


if __name__ == "__main__":
    unittest.main()

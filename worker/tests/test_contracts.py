from __future__ import annotations

import unittest

from timeline_for_audio_worker.contracts import InputItem, RunRequest, RunResult, RunStatus


class ContractsTests(unittest.TestCase):
    def test_run_request_round_trip_preserves_audio_pipeline_fields(self) -> None:
        request = RunRequest(
            schema_version=1,
            run_id="run-123",
            created_at="2026-03-23T18:00:00+09:00",
            output_root_id="default",
            output_root_path="/shared/outputs/default",
            profile="quality-first",
            compute_mode="gpu",
            pipeline_version="2026-04-29-v3-speaker-acoustic-units1",
            conversion_signature="sig-123",
            acoustic_unit_backend="zipa-large-crctc-300k-onnx-v1",
            acoustic_unit_model_id="anyspeech/zipa-large-crctc-300k",
            diarization_enabled=True,
            diarization_model_id="pyannote/speaker-diarization-community-1",
            vad_backend="ffmpeg-silencedetect",
            vad_model_id="ffmpeg-silencedetect-noise-35db",
            reprocess_duplicates=False,
            token_enabled=True,
            input_items=[
                InputItem(
                    input_id="scan-0001",
                    source_kind="mounted_root",
                    source_id="primary",
                    original_path="/shared/inputs/primary/example.wav",
                    display_name="example.wav",
                    size_bytes=1234,
                )
            ],
        )

        payload = request.to_dict()
        restored = RunRequest.from_dict(payload)

        self.assertEqual("run-123", restored.run_id)
        self.assertEqual("quality-first", restored.profile)
        self.assertEqual("gpu", restored.compute_mode)
        self.assertEqual("sig-123", payload["generation_signature"])
        self.assertEqual("sig-123", restored.conversion_signature)
        self.assertEqual("sig-123", restored.generation_signature)
        self.assertEqual(
            "zipa-large-crctc-300k-onnx-v1",
            restored.acoustic_unit_backend,
        )
        self.assertEqual(
            "anyspeech/zipa-large-crctc-300k",
            restored.acoustic_unit_model_id,
        )
        self.assertEqual("default", payload["vad_profile"])
        self.assertEqual("default", restored.vad_profile)
        self.assertTrue(restored.diarization_enabled)
        self.assertEqual(1, len(restored.input_items))
        self.assertEqual("example.wav", restored.input_items[0].display_name)

    def test_run_request_from_dict_reads_current_contract(self) -> None:
        restored = RunRequest.from_dict(
            {
                "schema_version": 1,
                "run_id": "run-123",
                "created_at": "2026-03-23T18:00:00+09:00",
                "output_root_id": "default",
                "output_root_path": "/shared/outputs/default",
                "profile": "quality-first",
                "compute_mode": "cpu",
                "pipeline_version": "2026-04-29-v3-speaker-acoustic-units1",
                "generation_signature": "sig-456",
                "acoustic_unit_backend": "zipa-large-crctc-300k-onnx-v1",
                "acoustic_unit_model_id": "anyspeech/zipa-large-crctc-300k",
                "diarization_enabled": True,
                "diarization_model_id": "pyannote/speaker-diarization-community-1",
                "vad_backend": "ffmpeg-silencedetect",
                "vad_model_id": "ffmpeg-silencedetect-noise-35db",
                "vad_profile": "loose",
                "reprocess_duplicates": True,
                "token_enabled": False,
                "input_items": [],
            }
        )

        self.assertEqual("sig-456", restored.generation_signature)
        self.assertEqual("cpu", restored.compute_mode)
        self.assertEqual("loose", restored.vad_profile)
        self.assertEqual("zipa-large-crctc-300k-onnx-v1", restored.acoustic_unit_backend)
        self.assertEqual("anyspeech/zipa-large-crctc-300k", restored.acoustic_unit_model_id)

    def test_run_status_from_dict_ignores_legacy_fields(self) -> None:
        restored = RunStatus.from_dict(
            {
                "run_id": "run-legacy",
                "state": "running",
                "videos_total": 3,
                "videos_done": 1,
                "videos_skipped": 1,
                "videos_failed": 0,
                "current_media": "media-1",
                "current_media_elapsed_sec": 12.5,
                "unknown_field": "ignored",
            }
        )

        self.assertEqual("run-legacy", restored.run_id)
        self.assertEqual("running", restored.state)
        self.assertEqual(3, restored.items_total)
        self.assertEqual(1, restored.items_done)
        self.assertEqual(1, restored.items_skipped)
        self.assertEqual(0, restored.items_failed)
        self.assertEqual("media-1", restored.current_item)
        self.assertEqual(12.5, restored.current_item_elapsed_sec)

    def test_run_result_from_dict_ignores_unknown_fields(self) -> None:
        restored = RunResult.from_dict(
            {
                "run_id": "run-legacy",
                "state": "completed",
                "processed_count": 2,
                "unknown_field": "ignored",
            }
        )

        self.assertEqual("run-legacy", restored.run_id)
        self.assertEqual("completed", restored.state)
        self.assertEqual(2, restored.processed_count)


if __name__ == "__main__":
    unittest.main()

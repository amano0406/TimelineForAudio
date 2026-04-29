from __future__ import annotations

import unittest

from timeline_for_audio_worker.contracts import InputItem, JobRequest


class ContractsTests(unittest.TestCase):
    def test_job_request_round_trip_preserves_audio_pipeline_fields(self) -> None:
        request = JobRequest(
            schema_version=1,
            job_id="run-123",
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
        restored = JobRequest.from_dict(payload)

        self.assertEqual("run-123", restored.job_id)
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

    def test_job_request_from_dict_reads_current_contract(self) -> None:
        restored = JobRequest.from_dict(
            {
                "schema_version": 1,
                "job_id": "run-123",
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


if __name__ == "__main__":
    unittest.main()

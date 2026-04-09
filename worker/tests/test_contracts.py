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
            processing_quality="high",
            pipeline_version="2026-04-05-mvp1",
            conversion_signature="sig-123",
            transcription_backend="faster-whisper",
            transcription_model_id="large-v3",
            transcription_initial_prompt="OpenAI Codex",
            transcript_normalization_mode="deterministic",
            transcript_normalization_glossary="Open AI => OpenAI",
            diarization_enabled=True,
            diarization_model_id="pyannote/speaker-diarization-community-1",
            vad_backend="silero-vad",
            vad_model_id="faster-whisper-default",
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
        self.assertEqual("high", restored.processing_quality)
        self.assertEqual("sig-123", restored.conversion_signature)
        self.assertEqual("OpenAI Codex", restored.transcription_initial_prompt)
        self.assertEqual("deterministic", restored.transcript_normalization_mode)
        self.assertEqual("Open AI => OpenAI", restored.transcript_normalization_glossary)
        self.assertTrue(restored.diarization_enabled)
        self.assertEqual(1, len(restored.input_items))
        self.assertEqual("example.wav", restored.input_items[0].display_name)


if __name__ == "__main__":
    unittest.main()

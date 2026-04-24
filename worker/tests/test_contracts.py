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
            pipeline_version="2026-04-05-mvp1",
            conversion_signature="sig-123",
            transcription_backend="faster-whisper",
            transcription_model_id="medium",
            supplemental_context_text="Known names: TimelineForAudio, WhisperX",
            context_builder_version="context-builder-v2",
            diarization_enabled=True,
            diarization_model_id="pyannote/speaker-diarization-community-1",
            vad_backend="silero-vad",
            vad_model_id="faster-whisper-default",
            reprocess_duplicates=False,
            token_enabled=True,
            language_hint="ja",
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
        self.assertEqual("ja", restored.language_hint)
        self.assertEqual("local-transformers-japanese-p2g-v1", restored.reconstruction_backend)
        self.assertEqual(
            "Respair/Japanese_Phoneme_to_Grapheme_LLM",
            restored.reconstruction_model_id,
        )
        self.assertEqual("ipa-turn-reconstruction-ja-v3", restored.reconstruction_prompt_version)
        self.assertTrue(restored.readable_text_enabled)
        self.assertEqual(
            "Known names: TimelineForAudio, WhisperX",
            restored.supplemental_context_text,
        )
        self.assertEqual("context-builder-v2", restored.context_builder_version)
        self.assertTrue(restored.diarization_enabled)
        self.assertEqual(1, len(restored.input_items))
        self.assertEqual("example.wav", restored.input_items[0].display_name)

    def test_job_request_from_dict_ignores_legacy_normalization_fields(self) -> None:
        restored = JobRequest.from_dict(
            {
                "schema_version": 1,
                "job_id": "run-123",
                "created_at": "2026-03-23T18:00:00+09:00",
                "output_root_id": "default",
                "output_root_path": "/shared/outputs/default",
                "profile": "quality-first",
                "compute_mode": "cpu",
                "processing_quality": "standard",
                "pipeline_version": "2026-04-10-2pass1",
                "generation_signature": "sig-456",
                "transcription_backend": "faster-whisper",
                "transcription_model_id": "medium",
                "supplemental_context_text": "prior terms",
                "second_pass_enabled": True,
                "context_builder_version": "context-builder-v2",
                "diarization_enabled": False,
                "vad_backend": "silero-vad",
                "vad_model_id": "faster-whisper-default",
                "reprocess_duplicates": True,
                "token_enabled": False,
                "language_hint": "ja,en",
                "input_items": [],
                "transcription_initial_prompt": "legacy prompt",
                "transcript_normalization_mode": "deterministic",
                "transcript_normalization_glossary": "legacy glossary",
            }
        )

        self.assertEqual("sig-456", restored.generation_signature)
        self.assertEqual("ja,en", restored.language_hint)
        self.assertEqual("ipa-aligned-text-fallback-v1", restored.reconstruction_backend)
        self.assertEqual("prior terms", restored.supplemental_context_text)
        self.assertEqual("context-builder-v2", restored.context_builder_version)

    def test_job_request_from_dict_can_disable_readable_text(self) -> None:
        restored = JobRequest.from_dict(
            {
                "schema_version": 1,
                "job_id": "run-ipa-only",
                "created_at": "2026-04-23T10:00:00+09:00",
                "output_root_id": "default",
                "output_root_path": "/shared/outputs/default",
                "profile": "quality-first",
                "compute_mode": "gpu",
                "pipeline_version": "2026-04-21-v2-ipa1",
                "generation_signature": "sig-ipa-only",
                "transcription_backend": "faster-whisper",
                "transcription_model_id": "medium",
                "context_builder_version": "context-builder-v2",
                "diarization_enabled": True,
                "vad_backend": "faster-whisper-builtin",
                "vad_model_id": "faster-whisper-default",
                "reprocess_duplicates": False,
                "token_enabled": True,
                "language_hint": "ja",
                "readable_text_enabled": False,
                "input_items": [],
            }
        )

        self.assertFalse(restored.readable_text_enabled)
        self.assertIsNone(restored.reconstruction_backend)
        self.assertIsNone(restored.reconstruction_model_id)
        self.assertIsNone(restored.reconstruction_prompt_version)


if __name__ == "__main__":
    unittest.main()

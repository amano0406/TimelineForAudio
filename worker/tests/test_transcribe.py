from __future__ import annotations

import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from timeline_for_audio_worker.transcribe import (
    _candidate_batch_sizes,
    _initial_batch_size,
    _is_cuda_oom,
    _is_cuda_runtime_failure,
    _load_model_with_fallback,
    _write_transcript_payload,
    transcribe_audio,
)


class TranscribeHelpersTests(unittest.TestCase):
    def test_high_quality_gpu_uses_conservative_initial_batch_size(self) -> None:
        self.assertEqual(4, _initial_batch_size("cuda", "high"))

    def test_standard_gpu_uses_larger_initial_batch_size(self) -> None:
        self.assertEqual(16, _initial_batch_size("cuda", "standard"))

    def test_candidate_batch_sizes_are_unique_and_descending(self) -> None:
        self.assertEqual([16, 12, 8, 6, 4, 2, 1], _candidate_batch_sizes(16))
        self.assertEqual([4, 2, 1], _candidate_batch_sizes(4))

    def test_cuda_oom_detection_handles_generic_cuda_error_text(self) -> None:
        error = RuntimeError("CUDA failed with error out of memory")
        self.assertTrue(_is_cuda_oom(error))
        self.assertFalse(_is_cuda_oom(RuntimeError("some other failure")))

    def test_cuda_runtime_failure_detection_handles_generic_cuda_errors(self) -> None:
        error = RuntimeError("CUDA failed with error unknown error")
        self.assertTrue(_is_cuda_runtime_failure(error))
        self.assertFalse(_is_cuda_runtime_failure(RuntimeError("plain cpu failure")))

    def test_gpu_model_load_falls_back_to_cpu_after_repeated_cuda_failures(self) -> None:
        warnings: list[str] = []
        calls: list[tuple[str, str]] = []

        class FakeCuda:
            @staticmethod
            def is_available() -> bool:
                return True

            @staticmethod
            def empty_cache() -> None:
                return None

        class FakeTorch:
            cuda = FakeCuda()

        def load_model(device: str, compute_type: str) -> object:
            calls.append((device, compute_type))
            if device == "cuda":
                raise RuntimeError("CUDA failed with error unknown error")
            return object()

        model, device, compute_type, batch_size = _load_model_with_fallback(
            load_model=load_model,
            torch_module=FakeTorch(),
            initial_device="cuda",
            initial_compute_type="float16",
            initial_batch_size=4,
            transcription_warnings=warnings,
        )

        self.assertIsNotNone(model)
        self.assertEqual("cpu", device)
        self.assertEqual("int8", compute_type)
        self.assertEqual(4, batch_size)
        self.assertEqual(
            [
                ("cuda", "float16"),
                ("cuda", "int8_float16"),
                ("cpu", "int8"),
            ],
            calls,
        )
        self.assertEqual(
            [
                "Primary GPU compute type failed to load; using int8_float16 instead.",
                "GPU model loading failed; transcription fell back to CPU.",
            ],
            warnings,
        )

    def test_write_transcript_payload_records_pass_metadata_and_context_prompt_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            payload = _write_transcript_payload(
                source_name="sample.wav",
                transcript_dir=transcript_dir,
                artifact_stem="pass2",
                metadata={
                    "status": "ok",
                    "pass_name": "pass2",
                    "model": "medium",
                    "processing_quality": "standard",
                    "device": "cpu",
                    "requested_compute_mode": "cpu",
                    "effective_compute_mode": "cpu",
                    "gpu_available": False,
                    "compute_type": "int8",
                    "batch_size": 4,
                    "language": "ja",
                    "language_probability": 0.99,
                    "alignment_used": False,
                    "context_prompt_configured": True,
                    "context_prompt_sha256": hashlib.sha256("known words".encode("utf-8")).hexdigest(),
                    "context_prompt_length": len("known words"),
                    "diarization_requested": True,
                    "diarization_used": False,
                    "diarization_error": "token missing",
                    "transcription_warnings": ["fallback"],
                    "segments": [
                        {
                            "index": 1,
                            "trimmed_start": 0.0,
                            "trimmed_end": 1.0,
                            "original_start": 0.0,
                            "original_end": 1.0,
                            "speaker": "SPEAKER_00",
                            "text": "hello",
                        }
                    ],
                    "speaker_turns": [],
                },
            )

            self.assertEqual("pass2", payload["pass_name"])
            self.assertTrue((transcript_dir / "pass2.json").exists())
            self.assertTrue((transcript_dir / "pass2.md").exists())
            rendered = (transcript_dir / "pass2.md").read_text(encoding="utf-8")
            self.assertIn("Pass: `pass2`", rendered)
            self.assertIn("Context prompt configured: `True`", rendered)
            self.assertIn("Diarization requested: `True`", rendered)

    @patch("timeline_for_audio_worker.transcribe.load_huggingface_token")
    @patch("timeline_for_audio_worker.transcribe.load_settings")
    def test_transcribe_audio_skips_diarization_when_not_requested(
        self,
        mock_load_settings,
        mock_load_token,
    ) -> None:
        mock_load_settings.return_value = {"huggingfaceTermsConfirmed": True}
        mock_load_token.return_value = "hf-test"

        class FakeSegment:
            def __init__(self, start: float, end: float, text: str) -> None:
                self.start = start
                self.end = end
                self.text = text

        class FakeInfo:
            language = "ja"
            language_probability = 0.99

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs) -> None:
                return None

        class FakeBatchedInferencePipeline:
            def __init__(self, model) -> None:
                self.model = model

            def transcribe(self, *args, **kwargs):
                return [FakeSegment(0.0, 1.0, "hello world")], FakeInfo()

        fake_faster_whisper = types.SimpleNamespace(
            BatchedInferencePipeline=FakeBatchedInferencePipeline,
            WhisperModel=FakeWhisperModel,
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules,
            {"faster_whisper": fake_faster_whisper},
            clear=False,
        ):
            payload = transcribe_audio(
                source_name="sample.wav",
                audio_path=Path(temp_dir) / "audio.wav",
                transcript_dir=Path(temp_dir) / "transcript",
                artifact_stem="pass1",
                pass_name="pass1",
                cut_map=[],
                compute_mode="cpu",
                processing_quality="standard",
                initial_prompt=None,
                diarization_enabled=False,
            )

        self.assertEqual("pass1", payload["pass_name"])
        self.assertFalse(payload["context_prompt_configured"])
        self.assertFalse(payload["diarization_requested"])
        self.assertFalse(payload["diarization_used"])

    @patch("timeline_for_audio_worker.transcribe.load_huggingface_token")
    @patch("timeline_for_audio_worker.transcribe.load_settings")
    def test_transcribe_audio_defers_diarization_even_when_requested_and_available(
        self,
        mock_load_settings,
        mock_load_token,
    ) -> None:
        mock_load_settings.return_value = {"huggingfaceTermsConfirmed": True}
        mock_load_token.return_value = "hf-test"

        class FakeSegment:
            def __init__(self, start: float, end: float, text: str) -> None:
                self.start = start
                self.end = end
                self.text = text

        class FakeInfo:
            language = "ja"
            language_probability = 0.99

        class FakeWhisperModel:
            def __init__(self, *args, **kwargs) -> None:
                return None

        class FakeBatchedInferencePipeline:
            def __init__(self, model) -> None:
                self.model = model

            def transcribe(self, *args, **kwargs):
                return [FakeSegment(0.0, 1.0, "hello world")], FakeInfo()

        fake_faster_whisper = types.SimpleNamespace(
            BatchedInferencePipeline=FakeBatchedInferencePipeline,
            WhisperModel=FakeWhisperModel,
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            sys.modules,
            {"faster_whisper": fake_faster_whisper},
            clear=False,
        ):
            payload = transcribe_audio(
                source_name="sample.wav",
                audio_path=Path(temp_dir) / "audio.wav",
                transcript_dir=Path(temp_dir) / "transcript",
                artifact_stem="pass2",
                pass_name="pass2",
                cut_map=[],
                compute_mode="cpu",
                processing_quality="standard",
                initial_prompt="known words",
                diarization_enabled=True,
            )

        self.assertEqual("pass2", payload["pass_name"])
        self.assertTrue(payload["context_prompt_configured"])
        self.assertTrue(payload["diarization_requested"])
        self.assertFalse(payload["diarization_used"])
        self.assertEqual("SPEAKER_00", payload["segments"][0]["speaker"])
        self.assertIsNone(payload["diarization_error"])


if __name__ == "__main__":
    unittest.main()

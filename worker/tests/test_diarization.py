from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from timeline_for_audio_worker.diarization import apply_speaker_diarization, merge_diarization_into_transcript


class DiarizationMergeTests(unittest.TestCase):
    def test_merge_diarization_assigns_word_level_speakers_and_preserves_text(self) -> None:
        payload = {
            "pass_name": "pass2",
            "segments": [
                {
                    "index": 1,
                    "speaker": "SPEAKER_00",
                    "text": "hello there",
                    "original_start": 0.0,
                    "original_end": 1.0,
                    "words": [
                        {"text": "hello", "original_start": 0.0, "original_end": 0.4},
                        {"text": "there", "original_start": 0.5, "original_end": 0.9},
                    ],
                },
                {
                    "index": 2,
                    "speaker": "SPEAKER_00",
                    "text": "general kenobi",
                    "original_start": 1.1,
                    "original_end": 2.0,
                    "words": [
                        {"text": "general", "original_start": 1.1, "original_end": 1.5},
                        {"text": "kenobi", "original_start": 1.5, "original_end": 2.0},
                    ],
                },
            ],
        }
        diarization_rows = [
            {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_01"},
            {"start": 1.0, "end": 2.1, "speaker": "SPEAKER_02"},
        ]

        merged = merge_diarization_into_transcript(payload, diarization_rows)

        self.assertTrue(merged["diarization_used"])
        self.assertEqual("word_overlap_midpoint", merged["speaker_assignment_method"])
        self.assertEqual("hello there general kenobi", " ".join(
            segment["text"] for segment in merged["speaker_segments"]
        ))
        self.assertEqual(["SPEAKER_01", "SPEAKER_02"], [segment["speaker"] for segment in merged["speaker_segments"]])
        self.assertEqual(
            "hello there general kenobi",
            " ".join(segment["text"] for segment in merged["raw_segments"]),
        )

    def test_merge_diarization_falls_back_to_segment_level_when_words_are_missing(self) -> None:
        payload = {
            "pass_name": "pass2",
            "segments": [
                {
                    "index": 1,
                    "speaker": "SPEAKER_00",
                    "text": "alpha beta",
                    "original_start": 0.0,
                    "original_end": 1.0,
                }
            ],
        }
        diarization_rows = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_03"}]

        merged = merge_diarization_into_transcript(payload, diarization_rows)

        self.assertTrue(merged["diarization_used"])
        self.assertEqual("segment_overlap_fallback", merged["speaker_assignment_method"])
        self.assertEqual("SPEAKER_03", merged["speaker_segments"][0]["speaker"])
        self.assertEqual("alpha beta", merged["speaker_segments"][0]["text"])

    def test_merge_diarization_returns_original_payload_when_turns_are_missing(self) -> None:
        payload = {
            "pass_name": "pass2",
            "segments": [
                {
                    "index": 1,
                    "speaker": "SPEAKER_00",
                    "text": "unchanged",
                    "original_start": 0.0,
                    "original_end": 1.0,
                }
            ],
        }

        merged = merge_diarization_into_transcript(payload, [])

        self.assertFalse(merged["diarization_used"])
        self.assertEqual("none", merged["speaker_assignment_method"])
        self.assertEqual(payload["segments"], merged["speaker_segments"])

    def test_apply_speaker_diarization_uses_preloaded_waveform_input(self) -> None:
        fake_calls: list[object] = []

        class FakeTurn:
            def __init__(self, start: float, end: float) -> None:
                self.start = start
                self.end = end

        class FakeAnnotation:
            def itertracks(self, yield_label: bool = True):
                yield FakeTurn(0.0, 1.0), None, "SPEAKER_01"

        class FakeDiarizer:
            def __call__(self, audio_input: object) -> FakeAnnotation:
                fake_calls.append(audio_input)
                return FakeAnnotation()

        fake_diarizer = FakeDiarizer()
        fake_pyannote_audio = ModuleType("pyannote.audio")

        class FakePipeline:
            @staticmethod
            def from_pretrained(model_id: str, token: str | None = None) -> FakeDiarizer:
                return fake_diarizer

        fake_pyannote_audio.Pipeline = FakePipeline

        fake_torchaudio = ModuleType("torchaudio")

        def fake_load(path: str):
            return object(), 16000

        fake_torchaudio.load = fake_load

        transcript_payload = {
            "pass_name": "pass2",
            "model": "large-v3",
            "processing_quality": "high",
            "language": "ja",
            "device": "cpu",
            "requested_compute_mode": "cpu",
            "effective_compute_mode": "cpu",
            "gpu_available": False,
            "compute_type": "int8",
            "alignment_used": False,
            "context_prompt_configured": True,
            "context_prompt_length": 12,
            "diarization_used": False,
            "transcription_warnings": [],
            "diarization_requested": True,
            "segments": [
                {
                    "index": 1,
                    "speaker": "SPEAKER_00",
                    "text": "alpha",
                    "original_start": 0.0,
                    "original_end": 1.0,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "sample.wav"
            audio_path.write_bytes(b"RIFF")
            transcript_dir = root / "transcript"
            analysis_dir = root / "analysis"

            with patch.dict("sys.modules", {"pyannote.audio": fake_pyannote_audio, "torchaudio": fake_torchaudio}):
                with patch("timeline_for_audio_worker.diarization.load_settings", return_value={"huggingfaceTermsConfirmed": True}):
                    with patch("timeline_for_audio_worker.diarization.load_huggingface_token", return_value="hf_test_token"):
                        enriched = apply_speaker_diarization(
                            source_name="sample.wav",
                            audio_path=audio_path,
                            transcript_dir=transcript_dir,
                            analysis_dir=analysis_dir,
                            transcript_payload=transcript_payload,
                            compute_mode="cpu",
                        )

        self.assertTrue(enriched["diarization_used"])
        self.assertEqual(1, len(fake_calls))
        self.assertIsInstance(fake_calls[0], dict)
        self.assertEqual(16000, fake_calls[0]["sample_rate"])
        self.assertIn("waveform", fake_calls[0])

    def test_apply_speaker_diarization_temporarily_forces_legacy_torch_checkpoint_load(self) -> None:
        seen_env_values: list[str | None] = []

        class FakeTurn:
            def __init__(self, start: float, end: float) -> None:
                self.start = start
                self.end = end

        class FakeAnnotation:
            def itertracks(self, yield_label: bool = True):
                yield FakeTurn(0.0, 1.0), None, "SPEAKER_01"

        class FakeDiarizer:
            def __call__(self, audio_input: object) -> FakeAnnotation:
                return FakeAnnotation()

        fake_pyannote_audio = ModuleType("pyannote.audio")

        class FakePipeline:
            @staticmethod
            def from_pretrained(model_id: str, token: str | None = None) -> FakeDiarizer:
                seen_env_values.append(os.environ.get("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"))
                return FakeDiarizer()

        fake_pyannote_audio.Pipeline = FakePipeline

        fake_torchaudio = ModuleType("torchaudio")

        def fake_load(path: str):
            return object(), 16000

        fake_torchaudio.load = fake_load

        transcript_payload = {
            "pass_name": "pass2",
            "model": "large-v3",
            "processing_quality": "high",
            "language": "ja",
            "device": "cpu",
            "requested_compute_mode": "cpu",
            "effective_compute_mode": "cpu",
            "gpu_available": False,
            "compute_type": "int8",
            "alignment_used": False,
            "context_prompt_configured": False,
            "context_prompt_length": 0,
            "diarization_used": False,
            "transcription_warnings": [],
            "diarization_requested": True,
            "segments": [
                {
                    "index": 1,
                    "speaker": "SPEAKER_00",
                    "text": "alpha",
                    "original_start": 0.0,
                    "original_end": 1.0,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            audio_path = root / "sample.wav"
            audio_path.write_bytes(b"RIFF")
            transcript_dir = root / "transcript"
            analysis_dir = root / "analysis"

            with patch.dict(
                "sys.modules",
                {"pyannote.audio": fake_pyannote_audio, "torchaudio": fake_torchaudio},
            ):
                with patch(
                    "timeline_for_audio_worker.diarization.load_settings",
                    return_value={"huggingfaceTermsConfirmed": True},
                ):
                    with patch(
                        "timeline_for_audio_worker.diarization.load_huggingface_token",
                        return_value="hf_test_token",
                    ):
                        with patch.dict(os.environ, {}, clear=False):
                            os.environ.pop("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", None)
                            apply_speaker_diarization(
                                source_name="sample.wav",
                                audio_path=audio_path,
                                transcript_dir=transcript_dir,
                                analysis_dir=analysis_dir,
                                transcript_payload=transcript_payload,
                                compute_mode="cpu",
                            )
                            self.assertNotIn(
                                "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD",
                                os.environ,
                            )

        self.assertEqual(["1"], seen_env_values)


if __name__ == "__main__":
    unittest.main()

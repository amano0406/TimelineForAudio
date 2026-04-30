from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import timeline_for_audio_worker.diarization as diarization
from timeline_for_audio_worker.diarization import generate_speaker_turns


class DiarizationTests(unittest.TestCase):
    def setUp(self) -> None:
        diarization._load_diarizer.cache_clear()

    def tearDown(self) -> None:
        diarization._load_diarizer.cache_clear()

    def test_generate_speaker_turns_uses_preloaded_waveform_input(self) -> None:
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

        fake_pyannote_audio = ModuleType("pyannote.audio")

        class FakePipeline:
            @staticmethod
            def from_pretrained(model_id: str, token: str | None = None) -> FakeDiarizer:
                return FakeDiarizer()

        fake_pyannote_audio.Pipeline = FakePipeline
        fake_torchaudio = ModuleType("torchaudio")
        fake_torchaudio.load = lambda path: (object(), 16000)

        with (
            patch.dict(
                "sys.modules",
                {"pyannote.audio": fake_pyannote_audio, "torchaudio": fake_torchaudio},
            ),
            patch(
                "timeline_for_audio_worker.diarization.load_huggingface_token",
                return_value="hf_test_token",
            ),
        ):
            payload = generate_speaker_turns(
                source_name="sample.wav",
                audio_path=Path("sample.wav"),
                compute_mode="cpu",
            )

        self.assertEqual("ok", payload["status"])
        self.assertEqual(1, payload["turn_count"])
        self.assertEqual("SPEAKER_01", payload["turns"][0]["speaker"])
        self.assertEqual(1, len(fake_calls))
        self.assertIsInstance(fake_calls[0], dict)
        self.assertEqual(16000, fake_calls[0]["sample_rate"])
        self.assertIn("waveform", fake_calls[0])

    def test_generate_speaker_turns_fails_when_required_token_is_missing(self) -> None:
        with (
            patch(
                "timeline_for_audio_worker.diarization.load_huggingface_token",
                return_value=None,
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "Hugging Face token is not configured"):
                generate_speaker_turns(
                    source_name="sample.wav",
                    audio_path=Path("sample.wav"),
                    compute_mode="cpu",
                )

    def test_generate_speaker_turns_temporarily_forces_legacy_torch_checkpoint_load(self) -> None:
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
        fake_torchaudio.load = lambda path: (object(), 16000)

        with (
            patch.dict(
                "sys.modules",
                {"pyannote.audio": fake_pyannote_audio, "torchaudio": fake_torchaudio},
            ),
            patch(
                "timeline_for_audio_worker.diarization.load_huggingface_token",
                return_value="hf_test_token",
            ),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", None)
            generate_speaker_turns(
                source_name="sample.wav",
                audio_path=Path("sample.wav"),
                compute_mode="cpu",
            )
            self.assertNotIn("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", os.environ)

        self.assertEqual(["1"], seen_env_values)


if __name__ == "__main__":
    unittest.main()

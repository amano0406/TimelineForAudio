from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import timeline_for_audio_worker.transcription as transcription
from timeline_for_audio_worker.transcription import best_speaker_for_interval


class TranscriptionTests(unittest.TestCase):
    def test_gpu_mode_uses_cuda_quantized_float16(self) -> None:
        self.assertEqual("cuda", transcription._device_for_compute_mode("gpu"))
        self.assertEqual("int8_float16", transcription._compute_type_for_compute_mode("gpu"))

    def test_cpu_mode_uses_cpu_int8(self) -> None:
        self.assertEqual("cpu", transcription._device_for_compute_mode("cpu"))
        self.assertEqual("int8", transcription._compute_type_for_compute_mode("cpu"))

    def test_generate_transcript_segments_preserves_segment_text(self) -> None:
        fake_info = SimpleNamespace(
            language="ja",
            language_probability=0.98,
            duration=4.0,
        )
        fake_segments = [
            SimpleNamespace(
                start=0.5,
                end=2.0,
                text=" こんにちは ",
                avg_logprob=-0.2,
                no_speech_prob=0.01,
            ),
            SimpleNamespace(
                start=2.0,
                end=4.0,
                text="よろしくお願いします",
                avg_logprob=-0.3,
                no_speech_prob=0.02,
            ),
        ]
        loaded = SimpleNamespace(
            model=SimpleNamespace(transcribe=lambda *args, **kwargs: (fake_segments, fake_info)),
            device="cuda",
            compute_type="float16",
        )

        with patch.object(transcription, "_load_transcription_model", return_value=loaded):
            result = transcription.generate_transcript_segments(
                audio_path="source.wav",
                compute_mode="gpu",
            )

        self.assertEqual("ok", result.status)
        self.assertEqual("ja", result.language)
        self.assertEqual("cuda", result.device)
        self.assertEqual("こんにちは", result.segments[0].text)
        self.assertEqual("よろしくお願いします", result.segments[1].text)

    def test_best_speaker_for_interval_uses_largest_overlap(self) -> None:
        speaker = best_speaker_for_interval(
            1.0,
            4.0,
            [
                {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"},
                {"start": 1.5, "end": 5.0, "speaker": "SPEAKER_01"},
            ],
        )

        self.assertEqual("SPEAKER_01", speaker)


if __name__ == "__main__":
    unittest.main()

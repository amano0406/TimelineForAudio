from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from timeline_for_audio_worker.ipa_backend import (
    AUDIO_TO_IPA_BACKEND,
    DEFAULT_IPA_BACKEND,
    EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND,
    IPAResult,
    IPATurn,
    align_ipa_turns_to_speakers,
    generate_audio_ipa_turns,
    generate_ipa_turns,
    resolve_ipa_backend,
)


class IPABackendTests(unittest.TestCase):
    def test_generate_audio_ipa_turns_decodes_audio_spans(self) -> None:
        with (
            patch("timeline_for_audio_worker.ipa_backend._load_audio_ipa_waveform", return_value=("wave", 10)),
            patch("timeline_for_audio_worker.ipa_backend._waveform_duration_seconds", return_value=2.0),
            patch("timeline_for_audio_worker.ipa_backend._slice_waveform", return_value="chunk"),
            patch(
                "timeline_for_audio_worker.ipa_backend._decode_audio_ipa_waveform",
                return_value=("konnitɕiwa", 0.87, AUDIO_TO_IPA_BACKEND, []),
            ) as decode,
        ):
            result = generate_audio_ipa_turns(
                audio_path="sample.wav",
                cut_map=[
                    {
                        "trimmed_start": 0.0,
                        "trimmed_end": 1.0,
                        "original_start": 12.0,
                        "original_end": 13.0,
                    }
                ],
                preferred_backend=None,
                compute_mode="cpu",
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(AUDIO_TO_IPA_BACKEND, result.backend_name)
        self.assertEqual("audio", result.source_type)
        self.assertEqual(1, len(result.turns))
        self.assertEqual(12.0, result.turns[0].start)
        self.assertEqual("/konnitɕiwa/", result.turns[0].ipa)
        self.assertEqual("cpu", decode.call_args.kwargs["compute_mode"])

    def test_generate_audio_ipa_turns_reports_backend_failure(self) -> None:
        with patch(
            "timeline_for_audio_worker.ipa_backend._load_audio_ipa_waveform",
            side_effect=RuntimeError("model missing"),
        ):
            result = generate_audio_ipa_turns(
                audio_path="sample.wav",
                cut_map=[],
                preferred_backend=None,
            )

        self.assertEqual("unavailable", result.status)
        self.assertEqual(AUDIO_TO_IPA_BACKEND, result.backend_name)
        self.assertTrue(any("model missing" in warning for warning in result.warnings))

    def test_align_ipa_turns_to_speakers_uses_best_overlap(self) -> None:
        result = align_ipa_turns_to_speakers(
            ipa_result=IPAResult(
                backend_name="audio-ipa",
                status="ok",
                source_type="audio",
                warnings=[],
                turns=[
                    IPATurn(index=1, start=0.2, end=0.9, speaker="", ipa="/a/"),
                    IPATurn(index=2, start=1.2, end=1.9, speaker="", ipa="/b/"),
                ],
            ),
            speaker_payload={
                "speaker_turns": [
                    {"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                    {"start": 1.0, "end": 2.0, "speaker": "SPEAKER_01"},
                ]
            },
        )

        self.assertEqual(["SPEAKER_00", "SPEAKER_01"], [turn.speaker for turn in result.turns])
        self.assertEqual("audio", result.source_type)

    def test_generate_ipa_turns_reads_segment_ipa_fields(self) -> None:
        result = generate_ipa_turns(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 1.2,
                        "original_end": 2.3,
                        "speaker": "SPEAKER_00",
                        "ipa": "/konnitɕiwa/",
                    }
                ]
            }
        )

        self.assertEqual("ok", result.status)
        self.assertEqual(1, len(result.turns))
        self.assertEqual("/konnitɕiwa/", result.turns[0].ipa)

    def test_generate_ipa_turns_derives_ipa_from_kana_text(self) -> None:
        result = generate_ipa_turns(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 1.2,
                        "original_end": 2.3,
                        "speaker": "SPEAKER_00",
                        "text": "サービス",
                    }
                ]
            }
        )

        self.assertEqual("ok", result.status)
        self.assertEqual(DEFAULT_IPA_BACKEND, result.backend_name)
        self.assertEqual(1, len(result.turns))
        self.assertEqual("/saabisɯ/", result.turns[0].ipa)

    def test_generate_ipa_turns_uses_ascii_fallback_for_latin_text(self) -> None:
        result = generate_ipa_turns(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 1.2,
                        "original_end": 2.3,
                        "speaker": "SPEAKER_00",
                        "text": "Shakt",
                    }
                ]
            }
        )

        self.assertEqual("ok", result.status)
        self.assertEqual("/ʃakt/", result.turns[0].ipa)

    def test_generate_ipa_turns_reports_unavailable_without_sudachi_for_kanji_text(self) -> None:
        with patch("timeline_for_audio_worker.ipa_backend._get_sudachi_tokenizer", return_value=None):
            result = generate_ipa_turns(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 1.2,
                            "original_end": 2.3,
                            "speaker": "SPEAKER_00",
                            "text": "結局",
                        }
                    ]
                }
            )

        self.assertEqual("unavailable", result.status)
        self.assertEqual([], result.turns)
        self.assertIn("SudachiPy", result.warnings[0])

    def test_resolve_ipa_backend_accepts_experimental_alias(self) -> None:
        self.assertEqual(
            EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND,
            resolve_ipa_backend("pyopenjtalk"),
        )

    def test_generate_ipa_turns_uses_pyopenjtalk_when_requested(self) -> None:
        fake_pyopenjtalk = types.SimpleNamespace(g2p=lambda text, kana=True: "サービス")
        with patch(
            "timeline_for_audio_worker.ipa_backend._get_pyopenjtalk_module",
            return_value=fake_pyopenjtalk,
        ):
            result = generate_ipa_turns(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 1.2,
                            "original_end": 2.3,
                            "speaker": "SPEAKER_00",
                            "text": "サービス",
                        }
                    ]
                },
                preferred_backend=EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND,
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND, result.backend_name)
        self.assertEqual("/saabisɯ/", result.turns[0].ipa)

    def test_generate_ipa_turns_falls_back_when_pyopenjtalk_is_unavailable(self) -> None:
        with patch(
            "timeline_for_audio_worker.ipa_backend._get_pyopenjtalk_module",
            return_value=None,
        ):
            result = generate_ipa_turns(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 1.2,
                            "original_end": 2.3,
                            "speaker": "SPEAKER_00",
                            "text": "サービス",
                        }
                    ]
                },
                preferred_backend=EXPERIMENTAL_PYOPENJTALK_IPA_BACKEND,
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(DEFAULT_IPA_BACKEND, result.backend_name)
        self.assertEqual("/saabisɯ/", result.turns[0].ipa)
        self.assertTrue(any("PyOpenJTalk" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()

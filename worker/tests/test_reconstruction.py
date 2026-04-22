from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from timeline_for_audio_worker.ipa_backend import IPAResult, IPATurn
from timeline_for_audio_worker.reconstruction import (
    LOCAL_LLM_RECONSTRUCTION_BACKEND,
    build_reconstruction_decoding,
    reconstruct_readable_text,
    resolve_reconstruction_backend,
    resolve_reconstruction_model_id,
    resolve_reconstruction_prompt_version,
)


class ReconstructionTests(unittest.TestCase):
    def test_reconstruct_readable_text_uses_ipa_aligned_segments(self) -> None:
        result = reconstruct_readable_text(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 1.2,
                        "original_end": 2.3,
                        "speaker": "SPEAKER_00",
                        "text": "N ob el Sh akt",
                    },
                    {
                        "index": 2,
                        "original_start": 2.4,
                        "original_end": 3.6,
                        "speaker": "SPEAKER_01",
                        "text": "B 2 C だよね?",
                    },
                ]
            },
            ipa_result=IPAResult(
                backend_name="sudachi-reading-ipa-v1",
                status="ok",
                warnings=[],
                turns=[
                    IPATurn(index=1, start=1.2, end=2.3, speaker="SPEAKER_00", ipa="/nobel shakt/"),
                    IPATurn(index=2, start=2.4, end=3.6, speaker="SPEAKER_01", ipa="/biitsɯsii da jone/"),
                ],
            ),
            language_hint="en",
        )

        self.assertEqual("ok", result.status)
        self.assertEqual("ipa-aligned-text-fallback-v1", result.backend_name)
        self.assertEqual(2, len(result.turns))
        self.assertEqual("NobelShakt", result.turns[0].text)
        self.assertEqual("B2C だよね?", result.turns[1].text)
        self.assertIn("fragmented short ASCII token runs", result.warnings[0])

    def test_reconstruct_readable_text_falls_back_to_segment_text_without_ipa(self) -> None:
        result = reconstruct_readable_text(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 1.2,
                        "original_end": 2.3,
                        "speaker": "SPEAKER_00",
                        "text": "こんにちは",
                    }
                ]
            },
            ipa_result=IPAResult(
                backend_name="sudachi-reading-ipa-v1",
                status="unavailable",
                warnings=["IPA turn data is not available from the current transcription payload."],
                turns=[],
            ),
            language_hint="ja",
        )

        self.assertEqual("ok", result.status)
        self.assertEqual("segment-text-fallback-v1", result.backend_name)
        self.assertEqual(1, len(result.turns))
        self.assertEqual("こんにちは", result.turns[0].text)

    def test_reconstruct_readable_text_uses_local_llm_when_japanese_hint_is_enabled(self) -> None:
        expected_result = reconstruct_readable_text(
            transcript_payload={
                "speaker_segments": [
                    {
                        "index": 1,
                        "original_start": 0.0,
                        "original_end": 1.0,
                        "speaker": "SPEAKER_00",
                        "text": "fallback",
                    }
                ]
            },
            ipa_result=IPAResult(
                backend_name="sudachi-reading-ipa-v1",
                status="ok",
                warnings=[],
                turns=[],
            ),
            language_hint="en",
        )
        expected_result.backend_name = LOCAL_LLM_RECONSTRUCTION_BACKEND

        with patch(
            "timeline_for_audio_worker.reconstruction._reconstruct_with_local_llm",
            return_value=expected_result,
        ) as mock_local_llm:
            result = reconstruct_readable_text(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 0.0,
                            "original_end": 1.0,
                            "speaker": "SPEAKER_00",
                            "text": "fallback",
                        }
                    ]
                },
                ipa_result=IPAResult(
                    backend_name="sudachi-reading-ipa-v1",
                    status="ok",
                    warnings=[],
                    turns=[
                        IPATurn(
                            index=1,
                            start=0.0,
                            end=1.0,
                            speaker="SPEAKER_00",
                            ipa="/konnitɕiwa/",
                        )
                    ],
                ),
                language_hint="ja,en",
                supplemental_context_text="Known spelling: TimelineForAudio",
                compute_mode="gpu",
            )

        self.assertEqual(LOCAL_LLM_RECONSTRUCTION_BACKEND, result.backend_name)
        mock_local_llm.assert_called_once()

    def test_reconstruct_readable_text_falls_back_when_local_llm_returns_prompt_leakage(self) -> None:
        fake_backend = SimpleNamespace(
            requested_compute_mode="gpu",
            effective_device="cuda",
        )
        with (
            patch(
                "timeline_for_audio_worker.reconstruction._load_local_llm_backend",
                return_value=fake_backend,
            ),
            patch(
                "timeline_for_audio_worker.reconstruction._generate_turn_text_with_local_llm",
                return_value=(
                    "The quick brown fox jumps over the lazy dog Time: 00:00:34.300 - 00:00:37.580 "
                    "ipa: /わたくしがいまやってるのが/",
                    False,
                ),
            ),
        ):
            result = reconstruct_readable_text(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 34.3,
                            "original_end": 37.58,
                            "speaker": "SPEAKER_01",
                            "text": "N ob el Sh akt",
                        }
                    ]
                },
                ipa_result=IPAResult(
                    backend_name="sudachi-reading-ipa-v1",
                    status="ok",
                    warnings=[],
                    turns=[
                        IPATurn(
                            index=1,
                            start=34.3,
                            end=37.58,
                            speaker="SPEAKER_01",
                            ipa="/watakɯɕi ga ima jatːeɾɯ no ga nobeɾɯɕea desɯ/",
                        )
                    ],
                ),
                language_hint="ja",
                compute_mode="gpu",
            )

        self.assertEqual("ok", result.status)
        self.assertEqual(1, len(result.turns))
        self.assertEqual("NobelShakt", result.turns[0].text)
        self.assertTrue(
            any("low-fidelity text" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_reconstruct_readable_text_preserves_reliable_aligned_japanese_turns(self) -> None:
        with (
            patch(
                "timeline_for_audio_worker.reconstruction._load_local_llm_backend",
                side_effect=AssertionError("local llm should not load for reliable aligned text"),
            ),
            patch(
                "timeline_for_audio_worker.reconstruction._generate_turn_text_with_local_llm",
                side_effect=AssertionError("local llm should not run for reliable aligned text"),
            ),
        ):
            result = reconstruct_readable_text(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 0.0,
                            "original_end": 1.0,
                            "speaker": "SPEAKER_00",
                            "text": "こんにちは、はじめまして。",
                        }
                    ]
                },
                ipa_result=IPAResult(
                    backend_name="sudachi-reading-ipa-v1",
                    status="ok",
                    warnings=[],
                    turns=[
                        IPATurn(
                            index=1,
                            start=0.0,
                            end=1.0,
                            speaker="SPEAKER_00",
                            ipa="/konnitɕiwa hadʑimemaɕite/",
                        )
                    ],
                ),
                language_hint="ja",
                compute_mode="gpu",
            )

        self.assertEqual("ok", result.status)
        self.assertEqual("こんにちは、はじめまして。", result.turns[0].text)
        self.assertTrue(
            any("preserved directly" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_reconstruct_readable_text_falls_back_when_local_llm_repeats_low_diversity_gibberish(self) -> None:
        fake_backend = SimpleNamespace(
            requested_compute_mode="gpu",
            effective_device="cuda",
        )
        with (
            patch(
                "timeline_for_audio_worker.reconstruction._load_local_llm_backend",
                return_value=fake_backend,
            ),
            patch(
                "timeline_for_audio_worker.reconstruction._generate_turn_text_with_local_llm",
                return_value=("ノイトルマihar 主水主水主水主水主水主水主水主水", False),
            ),
        ):
            result = reconstruct_readable_text(
                transcript_payload={
                    "speaker_segments": [
                        {
                            "index": 1,
                            "original_start": 0.0,
                            "original_end": 1.0,
                            "speaker": "SPEAKER_00",
                            "text": "N ob el Sh akt",
                        }
                    ]
                },
                ipa_result=IPAResult(
                    backend_name="sudachi-reading-ipa-v1",
                    status="ok",
                    warnings=[],
                    turns=[
                        IPATurn(
                            index=1,
                            start=0.0,
                            end=1.0,
                            speaker="SPEAKER_00",
                            ipa="/nobeɾɯ ɕakt/",
                        )
                    ],
                ),
                language_hint="ja",
                compute_mode="gpu",
            )

        self.assertEqual("ok", result.status)
        self.assertEqual("NobelShakt", result.turns[0].text)
        self.assertTrue(
            any("low-fidelity text" in warning for warning in result.warnings),
            result.warnings,
        )

    def test_reconstruction_profile_resolves_local_llm_for_japanese_hint(self) -> None:
        self.assertEqual(
            LOCAL_LLM_RECONSTRUCTION_BACKEND,
            resolve_reconstruction_backend("ja,en", "gpu"),
        )
        self.assertEqual(
            "Respair/Japanese_Phoneme_to_Grapheme_LLM",
            resolve_reconstruction_model_id("ja", "gpu"),
        )
        self.assertEqual(
            "ipa-turn-reconstruction-ja-v2",
            resolve_reconstruction_prompt_version("ja", "gpu"),
        )
        self.assertEqual(
            {
                "do_sample": False,
                "max_new_tokens": 128,
                "repetition_penalty": 1.02,
            },
            build_reconstruction_decoding("ja", "gpu"),
        )

    def test_reconstruction_profile_falls_back_for_explicit_non_japanese_hint(self) -> None:
        self.assertEqual("ipa-aligned-text-fallback-v1", resolve_reconstruction_backend("en", "gpu"))
        self.assertEqual("ipa-aligned-text-fallback-v1", resolve_reconstruction_backend("ja", "cpu"))
        self.assertIsNone(resolve_reconstruction_model_id("en", "gpu"))
        self.assertIsNone(resolve_reconstruction_model_id("ja", "cpu"))
        self.assertIsNone(resolve_reconstruction_prompt_version("en", "gpu"))
        self.assertIsNone(resolve_reconstruction_prompt_version("ja", "cpu"))
        self.assertIsNone(build_reconstruction_decoding("en", "gpu"))
        self.assertIsNone(build_reconstruction_decoding("ja", "cpu"))


if __name__ == "__main__":
    unittest.main()

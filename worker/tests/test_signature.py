from __future__ import annotations

import unittest

from timeline_for_audio_worker.signature import build_generation_signature


class SignatureTests(unittest.TestCase):
    def test_generation_signature_ignores_language_hint(self) -> None:
        left = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=True,
            language_hint="ja",
        )
        right = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=True,
            language_hint="en",
        )

        self.assertEqual(left, right)

    def test_generation_signature_ignores_readable_text_flag(self) -> None:
        full_output = build_generation_signature(
            compute_mode="gpu",
            diarization_enabled=True,
            language_hint="ja",
            readable_text_enabled=True,
        )
        ipa_only = build_generation_signature(
            compute_mode="gpu",
            diarization_enabled=True,
            language_hint="ja",
            readable_text_enabled=False,
        )

        self.assertEqual(full_output, ipa_only)

    def test_generation_signature_ignores_ipa_backend(self) -> None:
        sudachi = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=True,
            language_hint="ja",
            ipa_backend="sudachi",
        )
        pyopenjtalk = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=True,
            language_hint="ja",
            ipa_backend="pyopenjtalk",
        )

        self.assertEqual(sudachi, pyopenjtalk)

    def test_generation_signature_changes_when_vad_profile_changes(self) -> None:
        default = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja",
            vad_profile="default",
        )
        loose = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja",
            vad_profile="loose",
        )

        self.assertNotEqual(default, loose)


if __name__ == "__main__":
    unittest.main()

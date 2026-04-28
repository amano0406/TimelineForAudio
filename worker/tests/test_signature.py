from __future__ import annotations

import unittest

from timeline_for_audio_worker.signature import build_generation_signature


class SignatureTests(unittest.TestCase):
    def test_generation_signature_changes_when_language_hint_changes(self) -> None:
        left = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja",
        )
        right = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="en",
        )

        self.assertNotEqual(left, right)

    def test_generation_signature_normalizes_language_hint(self) -> None:
        left = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="JA\r\nEN",
        )
        right = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja\nen",
        )

        self.assertEqual(left, right)

    def test_generation_signature_changes_when_readable_text_is_disabled(self) -> None:
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

        self.assertNotEqual(full_output, ipa_only)

    def test_generation_signature_changes_when_ipa_backend_changes(self) -> None:
        sudachi = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja",
            ipa_backend="sudachi",
        )
        pyopenjtalk = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            language_hint="ja",
            ipa_backend="pyopenjtalk",
        )

        self.assertNotEqual(sudachi, pyopenjtalk)

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

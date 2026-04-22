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


if __name__ == "__main__":
    unittest.main()

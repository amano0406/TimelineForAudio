from __future__ import annotations

import unittest

from timeline_for_audio_worker.signature import build_generation_signature


class SignatureTests(unittest.TestCase):
    def test_generation_signature_changes_when_compute_mode_changes(self) -> None:
        cpu = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=True,
        )
        gpu = build_generation_signature(
            compute_mode="gpu",
            diarization_enabled=True,
        )

        self.assertNotEqual(cpu, gpu)

    def test_generation_signature_changes_when_vad_profile_changes(self) -> None:
        default = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            vad_profile="default",
        )
        loose = build_generation_signature(
            compute_mode="cpu",
            diarization_enabled=False,
            vad_profile="loose",
        )

        self.assertNotEqual(default, loose)

    def test_generation_signature_is_stable_for_same_settings(self) -> None:
        left = build_generation_signature(
            compute_mode="gpu",
            diarization_enabled=True,
            vad_profile="default",
        )
        right = build_generation_signature(
            compute_mode="gpu",
            diarization_enabled=True,
            vad_profile="default",
        )

        self.assertEqual(left, right)


if __name__ == "__main__":
    unittest.main()

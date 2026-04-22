from __future__ import annotations

import unittest
from unittest.mock import patch

from timeline_for_audio_worker.ipa_backend import generate_ipa_turns


class IPABackendTests(unittest.TestCase):
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
        self.assertEqual("sudachi-reading-ipa-v1", result.backend_name)
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


if __name__ == "__main__":
    unittest.main()

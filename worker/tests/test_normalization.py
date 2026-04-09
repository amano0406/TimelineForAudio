from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.normalization import normalize_transcript_artifacts


class NormalizationTests(unittest.TestCase):
    def test_normalization_applies_speaker_and_text_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            normalized_payload, report_payload = normalize_transcript_artifacts(
                source_name="sample.wav",
                transcript_dir=transcript_dir,
                raw_payload={
                    "status": "ok",
                    "segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "text": "Open AI を 使う",
                            "original_start": 0.0,
                            "original_end": 1.0,
                        }
                    ],
                },
                normalization_mode="deterministic",
                glossary_text="\n".join(
                    [
                        "speaker:SPEAKER_00 => Alice",
                        "Open AI => OpenAI",
                        "OpenAI",
                    ]
                ),
            )

            self.assertEqual("Alice", normalized_payload["segments"][0]["speaker"])
            self.assertEqual("OpenAI を 使う", normalized_payload["segments"][0]["text"])
            self.assertEqual(1, report_payload["changed_segment_count"])
            self.assertEqual(1, report_payload["context_terms"][0]["occurrence_count"])
            self.assertTrue((transcript_dir / "normalized.json").exists())
            self.assertTrue((transcript_dir / "normalized.md").exists())
            self.assertTrue((transcript_dir / "normalization_report.json").exists())
            self.assertTrue((transcript_dir / "normalization_report.md").exists())

            persisted = json.loads(
                (transcript_dir / "normalization_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual("deterministic", persisted["mode"])

    def test_normalization_off_preserves_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            normalized_payload, report_payload = normalize_transcript_artifacts(
                source_name="sample.wav",
                transcript_dir=transcript_dir,
                raw_payload={
                    "status": "ok",
                    "segments": [
                        {
                            "speaker": "SPEAKER_00",
                            "text": "Open AI を 使う",
                            "original_start": 0.0,
                            "original_end": 1.0,
                        }
                    ],
                },
                normalization_mode="off",
                glossary_text="Open AI => OpenAI",
            )

            self.assertEqual("Open AI を 使う", normalized_payload["segments"][0]["text"])
            self.assertEqual(0, report_payload["changed_segment_count"])


if __name__ == "__main__":
    unittest.main()

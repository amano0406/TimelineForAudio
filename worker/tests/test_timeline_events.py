from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from timeline_for_audio_worker.timeline_events import build_timeline_events, write_timeline_events


class TimelineEventsTests(unittest.TestCase):
    def test_build_timeline_events_preserves_original_time_gaps(self) -> None:
        payload = build_timeline_events(
            source_name="sample.wav",
            duration_seconds=10.0,
            cut_map=[
                {
                    "original_start": 2.0,
                    "original_end": 4.0,
                    "trimmed_start": 0.0,
                    "trimmed_end": 2.0,
                },
                {
                    "original_start": 7.0,
                    "original_end": 8.5,
                    "trimmed_start": 2.0,
                    "trimmed_end": 3.5,
                },
            ],
        )

        self.assertEqual(2, payload["speech_candidate_count"])
        self.assertEqual(3, payload["silence_or_noise_candidate_count"])
        self.assertEqual(
            [
                "silence_or_noise_candidate",
                "speech_candidate",
                "silence_or_noise_candidate",
                "speech_candidate",
                "silence_or_noise_candidate",
            ],
            [row["event_type"] for row in payload["events"]],
        )
        self.assertEqual("00:00:02.000 - 00:00:04.000", payload["events"][1]["time_label"])

    def test_write_timeline_events_writes_json_and_markdown(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            payload = write_timeline_events(
                source_info={"display_name": "sample.wav"},
                source_name="sample.wav",
                duration_seconds=5.0,
                cut_map=[
                    {
                        "original_start": 1.0,
                        "original_end": 3.0,
                        "trimmed_start": 0.0,
                        "trimmed_end": 2.0,
                    }
                ],
                output_dir=output_dir,
            )

            self.assertTrue((output_dir / "timeline_events.json").exists())
            markdown = (output_dir / "Timeline Events.md").read_text(encoding="utf-8")
            self.assertIn("# Timeline Events", markdown)
            self.assertIn("Type: `speech_candidate`", markdown)
            self.assertEqual(1, payload["speech_candidate_count"])


if __name__ == "__main__":
    unittest.main()

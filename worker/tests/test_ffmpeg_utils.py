from __future__ import annotations

import unittest
from pathlib import Path

from audio2timeline_worker.ffmpeg_utils import summarize_probe_payload


class ProbeSummaryTests(unittest.TestCase):
    def test_summarize_probe_payload_extracts_audio_metadata(self) -> None:
        payload = {
            "format": {
                "duration": "120.5",
                "size": "987654321",
                "bit_rate": "256000",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                "tags": {
                    "creation_time": "2026-03-25T01:02:03Z",
                },
            },
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "channels": 2,
                    "sample_rate": "48000",
                },
            ],
        }

        summary = summarize_probe_payload(payload, Path("/tmp/example.m4a"))

        self.assertEqual(120.5, summary["duration_seconds"])
        self.assertEqual(987654321, summary["size_bytes"])
        self.assertEqual("mov", summary["container_name"])
        self.assertEqual(".m4a", summary["extension"])
        self.assertEqual("aac", summary["audio_codec"])
        self.assertEqual(2, summary["audio_channels"])
        self.assertEqual(48000, summary["audio_sample_rate"])
        self.assertEqual(256000, summary["bitrate"])
        self.assertEqual("2026-03-25T01:02:03Z", summary["captured_at"])


if __name__ == "__main__":
    unittest.main()

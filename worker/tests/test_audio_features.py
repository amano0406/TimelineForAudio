from __future__ import annotations

import unittest

from audio2timeline_worker.audio_features import (
    build_diarization_summaries,
    build_overlap_summary,
)


class AudioFeatureHelpersTests(unittest.TestCase):
    def test_build_overlap_summary_counts_interruptions(self) -> None:
        summary = build_overlap_summary(
            [
                {
                    "speaker": "SPEAKER_00",
                    "text": "hello",
                    "original_start": 0.0,
                    "original_end": 2.0,
                },
                {
                    "speaker": "SPEAKER_01",
                    "text": "world",
                    "original_start": 1.8,
                    "original_end": 3.0,
                },
                {
                    "speaker": "SPEAKER_01",
                    "text": "again",
                    "original_start": 3.1,
                    "original_end": 4.0,
                },
            ]
        )

        self.assertTrue(summary["available"])
        self.assertEqual(1, summary["speaker_change_count"])
        self.assertEqual(1, summary["overlap_segment_count"])
        self.assertEqual(1, summary["interruption_count"])
        self.assertAlmostEqual(0.2, summary["total_overlap_seconds"], places=3)

    def test_build_diarization_summaries_returns_heuristics(self) -> None:
        transcript_payload = {
            "diarization_used": True,
            "speaker_turns": [
                {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
                {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
            ],
            "segments": [
                {
                    "speaker": "SPEAKER_00",
                    "text": "hello",
                    "original_start": 0.0,
                    "original_end": 1.8,
                },
                {
                    "speaker": "SPEAKER_01",
                    "text": "world",
                    "original_start": 2.1,
                    "original_end": 3.8,
                },
            ],
        }
        overlap_summary = build_overlap_summary(transcript_payload["segments"])
        confidence, quality = build_diarization_summaries(
            transcript_payload,
            duration_seconds=4.0,
            overlap_summary=overlap_summary,
        )

        self.assertTrue(confidence["available"])
        self.assertGreaterEqual(confidence["mean_best_overlap_ratio"], 0.8)
        self.assertEqual(0, confidence["low_confidence_segments"])
        self.assertTrue(quality["available"])
        self.assertEqual("high", quality["quality_band"])
        self.assertEqual(2, quality["speaker_turn_count"])

    def test_build_diarization_summaries_handles_disabled_diarization(self) -> None:
        confidence, quality = build_diarization_summaries(
            {"diarization_used": False, "segments": []},
            duration_seconds=10.0,
            overlap_summary=build_overlap_summary([]),
        )

        self.assertFalse(confidence["available"])
        self.assertFalse(quality["available"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.timeline import render_timeline


class TimelineTests(unittest.TestCase):
    def test_render_timeline_uses_original_timestamps_and_audio_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "timeline.md"
            render_timeline(
                output_path=output_path,
                source_info={
                    "original_path": "C:/audio.wav",
                    "audio_id": "sample",
                    "duration_seconds": 120.0,
                    "model_id": "medium",
                },
                transcript_payload={
                    "diarization_used": True,
                    "normalization": {
                        "mode": "deterministic",
                        "changed_segment_count": 1,
                    },
                    "segments": [
                        {
                            "speaker": "SPEAKER_01",
                            "text": "hello world",
                            "original_start": 12.345,
                            "original_end": 15.678,
                        }
                    ],
                },
                speaker_summary={"speaker_count": 1},
                audio_feature_summary={
                    "pause_summary": {"total_silence_seconds": 1.2},
                    "loudness_summary": {"integrated_lufs": -18.2},
                    "speaking_rate_summary": {"estimated_units_per_minute": 120.0},
                    "pitch_summary": {"median_hz": 180.0},
                    "overlap_summary": {"overlap_segment_count": 1, "interruption_count": 1},
                    "speaker_confidence_summary": {"mean_best_overlap_ratio": 0.82},
                    "diarization_quality_summary": {"quality_band": "medium"},
                },
            )

            text = output_path.read_text(encoding="utf-8")
            self.assertIn("Audio Timeline", text)
            self.assertIn("00:00:12.345 - 00:00:15.678", text)
            self.assertIn("Speaker: `SPEAKER_01`", text)
            self.assertIn("Text: hello world", text)
            self.assertIn("Median pitch Hz", text)
            self.assertIn("Interruptions", text)
            self.assertIn("Diarization quality", text)
            self.assertIn("Transcript normalization mode", text)


if __name__ == "__main__":
    unittest.main()

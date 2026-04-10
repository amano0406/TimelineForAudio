from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.timeline import render_timeline


class TimelineTests(unittest.TestCase):
    def test_render_timeline_uses_pass2_metadata_and_audio_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "timeline.md"
            render_timeline(
                output_path=output_path,
                source_info={
                    "original_path": "C:/audio.wav",
                    "audio_id": "sample",
                    "duration_seconds": 120.0,
                    "model_id": "medium",
                    "timeline_transcript_variant": "pass2",
                    "supplemental_context_configured": True,
                },
                transcript_payload={
                    "pass_name": "pass2",
                    "diarization_used": True,
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
            self.assertIn("Transcript source: `pass2`", text)
            self.assertIn("Supplemental context configured: `True`", text)
            self.assertIn("00:00:12.345 - 00:00:15.678", text)
            self.assertIn("Speaker: `SPEAKER_01`", text)
            self.assertIn("Text: hello world", text)
            self.assertIn("Median pitch Hz", text)
            self.assertIn("Interruptions", text)
            self.assertIn("Diarization quality", text)

    def test_render_timeline_keeps_chronological_order_with_stable_sort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "timeline.md"
            render_timeline(
                output_path=output_path,
                source_info={"original_path": "C:/audio.wav", "audio_id": "sample", "duration_seconds": 10.0},
                transcript_payload={
                    "pass_name": "pass2",
                    "diarization_used": False,
                    "segments": [
                        {"speaker": "SPEAKER_02", "text": "later", "original_start": 5.0, "original_end": 6.0},
                        {"speaker": "SPEAKER_00", "text": "first", "original_start": 1.0, "original_end": 2.0},
                        {"speaker": "SPEAKER_01", "text": "same-start-a", "original_start": 3.0, "original_end": 3.5},
                        {"speaker": "SPEAKER_02", "text": "same-start-b", "original_start": 3.0, "original_end": 4.0},
                    ],
                },
                speaker_summary={"speaker_count": 3},
                audio_feature_summary={
                    "pause_summary": {"total_silence_seconds": 0.0},
                    "loudness_summary": {"integrated_lufs": -18.2},
                    "speaking_rate_summary": {"estimated_units_per_minute": 120.0},
                    "pitch_summary": {"median_hz": 180.0},
                    "overlap_summary": {"overlap_segment_count": 1, "interruption_count": 1},
                    "speaker_confidence_summary": {"mean_best_overlap_ratio": None},
                    "diarization_quality_summary": {"quality_band": None},
                },
            )

            text = output_path.read_text(encoding="utf-8")
            first_index = text.index("Text: first")
            same_start_a_index = text.index("Text: same-start-a")
            same_start_b_index = text.index("Text: same-start-b")
            later_index = text.index("Text: later")
            self.assertLess(first_index, same_start_a_index)
            self.assertLess(same_start_a_index, same_start_b_index)
            self.assertLess(same_start_b_index, later_index)


if __name__ == "__main__":
    unittest.main()

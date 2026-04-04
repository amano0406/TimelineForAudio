from __future__ import annotations

import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from audio2timeline_worker.screens import (
    candidate_timestamps,
    extract_screens,
    normalize_processing_quality,
    resolve_caption_model_id_for_quality,
)
from audio2timeline_worker.config import ChangeDetectionConfig


class CandidateTimestampsTests(unittest.TestCase):
    def test_short_videos_keep_single_zero_timestamp(self) -> None:
        self.assertEqual(candidate_timestamps(0.8), [0.0])

    def test_last_timestamp_is_clamped_before_duration(self) -> None:
        timestamps = candidate_timestamps(8.783)
        self.assertGreater(len(timestamps), 1)
        self.assertLess(timestamps[-1], 8.783)
        self.assertAlmostEqual(timestamps[-1], 8.733, places=3)


class ProcessingQualityTests(unittest.TestCase):
    def test_normalize_processing_quality_defaults_to_standard(self) -> None:
        self.assertEqual(normalize_processing_quality(None), "standard")
        self.assertEqual(normalize_processing_quality(""), "standard")
        self.assertEqual(normalize_processing_quality("medium"), "standard")

    def test_normalize_processing_quality_accepts_high(self) -> None:
        self.assertEqual(normalize_processing_quality("high"), "high")
        self.assertEqual(normalize_processing_quality("HIGH"), "high")

    def test_caption_model_stays_on_stable_default(self) -> None:
        self.assertEqual(
            resolve_caption_model_id_for_quality("standard"),
            "florence-community/Florence-2-base",
        )
        self.assertEqual(
            resolve_caption_model_id_for_quality("high"),
            "florence-community/Florence-2-base",
        )


class ExtractScreensTests(unittest.TestCase):
    def test_extract_screens_retries_failed_timestamp_and_continues(self) -> None:
        attempts: list[float] = []

        def fake_extract_frame(video_path: Path, image_path: Path, timestamp: float) -> None:
            attempts.append(timestamp)
            if len(attempts) == 1:
                raise subprocess.CalledProcessError(234, ["ffmpeg"], stderr="decode failure")
            image_path.write_bytes(b"jpg")

        with tempfile.TemporaryDirectory() as tmpdir:
            screen_dir = Path(tmpdir) / "screen"
            fake_change_detection = types.SimpleNamespace(
                compare_images=lambda prev, curr, thresholds: types.SimpleNamespace(
                    classification="same",
                    phash_distance=0,
                    mean_diff=0.0,
                )
            )
            with (
                patch("audio2timeline_worker.screens.candidate_timestamps", return_value=[596.473]),
                patch("audio2timeline_worker.screens.extract_frame", side_effect=fake_extract_frame),
                patch("audio2timeline_worker.screens._load_ocr_components", return_value=(None, None)),
                patch.dict("sys.modules", {"audio2timeline_worker.change_detection": fake_change_detection}),
            ):
                notes, diffs, warnings = extract_screens(
                    video_path=Path("/tmp/video.mp4"),
                    screen_dir=screen_dir,
                    duration_seconds=600.0,
                    thresholds=ChangeDetectionConfig(),
                    compute_mode="cpu",
                    processing_quality="standard",
                )

        self.assertEqual(warnings, [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(attempts[:2], [596.473, 596.223])
        self.assertAlmostEqual(notes[0]["timestamp"], 596.223, places=3)
        self.assertAlmostEqual(diffs[0]["timestamp"], 596.223, places=3)

    def test_extract_screens_skips_unrecoverable_frame_and_returns_warning(self) -> None:
        def fake_extract_frame(video_path: Path, image_path: Path, timestamp: float) -> None:
            if abs(timestamp - 20.0) > 0.001:
                raise subprocess.CalledProcessError(234, ["ffmpeg"], stderr="bad frame")
            image_path.write_bytes(b"jpg")

        with tempfile.TemporaryDirectory() as tmpdir:
            screen_dir = Path(tmpdir) / "screen"
            fake_change_detection = types.SimpleNamespace(
                compare_images=lambda prev, curr, thresholds: types.SimpleNamespace(
                    classification="same",
                    phash_distance=0,
                    mean_diff=0.0,
                )
            )
            with (
                patch("audio2timeline_worker.screens.candidate_timestamps", return_value=[10.0, 20.0]),
                patch("audio2timeline_worker.screens.extract_frame", side_effect=fake_extract_frame),
                patch("audio2timeline_worker.screens._load_ocr_components", return_value=(None, None)),
                patch.dict("sys.modules", {"audio2timeline_worker.change_detection": fake_change_detection}),
            ):
                notes, diffs, warnings = extract_screens(
                    video_path=Path("/tmp/video.mp4"),
                    screen_dir=screen_dir,
                    duration_seconds=30.0,
                    thresholds=ChangeDetectionConfig(),
                    compute_mode="cpu",
                    processing_quality="standard",
                )

        self.assertEqual(len(warnings), 1)
        self.assertIn("Skipped screenshot at 10.000s", warnings[0])
        self.assertEqual(len(notes), 1)
        self.assertEqual(len(diffs), 1)
        self.assertAlmostEqual(notes[0]["timestamp"], 20.0, places=3)


if __name__ == "__main__":
    unittest.main()

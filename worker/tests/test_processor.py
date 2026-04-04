from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from audio2timeline_worker import processor


class ProcessorQueueTests(unittest.TestCase):
    def test_resolve_duplicate_timeline_path_returns_none_for_stale_catalog_entry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate = {
                "timeline_path": str(root / "missing-timeline.md"),
                "run_dir": str(root / "missing-run"),
                "media_id": "sample-media",
            }

            self.assertIsNone(processor._resolve_duplicate_timeline_path(duplicate))

    def test_resolve_duplicate_timeline_path_uses_run_dir_when_timeline_path_is_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            timeline_path = root / "job-1" / "media" / "sample-media" / "timeline" / "timeline.md"
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            timeline_path.write_text("# Timeline\n", encoding="utf-8")

            duplicate = {
                "timeline_path": str(root / "stale-timeline.md"),
                "run_dir": str(root / "job-1"),
                "media_id": "sample-media",
            }

            self.assertEqual(timeline_path, processor._resolve_duplicate_timeline_path(duplicate))

    def test_process_job_waits_for_running_job_before_picking_pending(self) -> None:
        with (
            patch.object(processor, "_collect_running_jobs", return_value=[Path("/tmp/run-1")]),
            patch.object(processor, "_collect_pending_jobs") as collect_pending,
        ):
            self.assertFalse(processor.process_job())
            collect_pending.assert_not_called()


if __name__ == "__main__":
    unittest.main()

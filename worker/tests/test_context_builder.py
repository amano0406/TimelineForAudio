from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.context_builder import build_context_documents


class ContextBuilderTests(unittest.TestCase):
    def test_build_context_documents_writes_primary_secondary_and_merged_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            report = build_context_documents(
                transcript_dir=transcript_dir,
                transcript_payload={
                    "segments": [
                        {"text": "OpenAI Codex で TimelineForAudio を確認する", "start": 0.0, "end": 3.0},
                        {"text": "Issue CASE-0001 と build 8765 の確認", "start": 3.0, "end": 6.0},
                    ]
                },
                supplemental_context_text="既知表記: TimelineForAudio\nKnown code: 8765",
                max_merged_length=1000,
            )

            self.assertTrue((transcript_dir / "context_primary.txt").exists())
            self.assertTrue((transcript_dir / "context_secondary.txt").exists())
            self.assertTrue((transcript_dir / "context_merged.txt").exists())
            self.assertTrue((transcript_dir / "context_report.json").exists())
            merged = (transcript_dir / "context_merged.txt").read_text(encoding="utf-8")
            self.assertIn("TimelineForAudio", merged)
            self.assertIn("Known code: 8765", merged)
            self.assertEqual(len(merged), report["merged_context_length"])

    def test_build_context_documents_truncates_merged_context_and_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            report = build_context_documents(
                transcript_dir=transcript_dir,
                transcript_payload={"segments": [{"text": "alpha beta gamma delta " * 30}]},
                supplemental_context_text="omega " * 30,
                max_merged_length=120,
            )

            merged = (transcript_dir / "context_merged.txt").read_text(encoding="utf-8")
            self.assertLessEqual(len(merged), 120)
            self.assertTrue(report["merged_context_truncated"])

    def test_build_context_documents_handles_empty_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            transcript_dir = Path(temp_dir)
            report = build_context_documents(
                transcript_dir=transcript_dir,
                transcript_payload={"segments": []},
                supplemental_context_text=None,
                max_merged_length=120,
            )

            self.assertEqual("", (transcript_dir / "context_primary.txt").read_text(encoding="utf-8"))
            self.assertFalse((transcript_dir / "context_secondary.txt").exists())
            self.assertEqual("", (transcript_dir / "context_merged.txt").read_text(encoding="utf-8"))
            loaded = json.loads((transcript_dir / "context_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report, loaded)

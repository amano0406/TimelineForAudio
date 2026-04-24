from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from timeline_for_audio_worker.artifacts import render_ipa, render_readable_text, write_media_artifacts_index


class ArtifactsTests(unittest.TestCase):
    def test_render_readable_text_writes_turn_markdown(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "readable-text" / "Readable Text.md"
            rendered = render_readable_text(
                output_path=output_path,
                source_info={
                    "original_path": r"C:\Users\amano\Videos\2026-04-01 12-55-07.wav",
                    "display_name": "2026-04-01 12-55-07.wav",
                    "language_hint": "ja,en",
                },
                speaker_count=2,
                speaker_count_status="confirmed",
                warnings=["Readable text cleanup merged fragmented short ASCII token runs in some turns."],
                turns=[
                    {
                        "start": 12.34,
                        "end": 15.98,
                        "speaker": "SPEAKER_00",
                        "text": "  こんにちは、 はじめまして。 ",
                    },
                    {
                        "start": 16.12,
                        "end": 18.44,
                        "speaker": "SPEAKER_01",
                        "text": "よろしくお願いします。",
                    },
                ],
            )

            self.assertTrue(output_path.exists())
            self.assertIn("# Readable Text", rendered)
            self.assertIn("- File: `2026-04-01 12-55-07`", rendered)
            self.assertIn("- Source File: `2026-04-01 12-55-07.wav`", rendered)
            self.assertIn("- Speakers: `2`", rendered)
            self.assertIn("- Language Hint: `ja,en`", rendered)
            self.assertNotIn("Speaker Count Status", rendered)
            self.assertNotIn("## Notes", rendered)
            self.assertIn("### Turn 001", rendered)
            self.assertIn("Time: `00:00:12.340 - 00:00:15.980`", rendered)
            self.assertIn("Speaker: `SPEAKER_00`", rendered)
            self.assertIn("Text: こんにちは、 はじめまして。", rendered)

    def test_write_media_artifacts_index_writes_primary_kind(self) -> None:
        with TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "media" / "sample-001"
            media_dir.mkdir(parents=True)

            payload = write_media_artifacts_index(
                media_dir=media_dir,
                media_id="sample-001",
                primary_artifact_kind="readable_text",
                artifacts=[
                    {
                        "kind": "readable_text",
                        "title": "Readable Text",
                        "display_name": "可読テキスト",
                        "role": "primary",
                        "format": "md",
                        "relative_path": "readable-text/Readable Text.md",
                    }
                ],
            )

            self.assertEqual("readable_text", payload["primary_artifact_kind"])
            saved = json.loads((media_dir / "artifacts.json").read_text(encoding="utf-8"))
            self.assertEqual("sample-001", saved["media_id"])
            self.assertEqual("readable_text", saved["primary_artifact_kind"])

    def test_render_ipa_writes_turn_markdown(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "ipa" / "IPA.md"
            rendered = render_ipa(
                output_path=output_path,
                source_info={
                    "original_path": r"C:\Users\amano\Videos\2026-04-01 12-55-07.wav",
                    "display_name": "2026-04-01 12-55-07.wav",
                    "language_hint": "ja,en",
                },
                backend_name="segment-ipa-passthrough",
                status="ok",
                speaker_count=1,
                speaker_count_status="confirmed",
                turns=[
                    {
                        "start": 12.34,
                        "end": 15.98,
                        "speaker": "SPEAKER_00",
                        "ipa": "/konnitɕiwa hajimemaɕite/",
                    }
                ],
            )

            self.assertTrue(output_path.exists())
            self.assertIn("# IPA", rendered)
            self.assertIn("- File: `2026-04-01 12-55-07`", rendered)
            self.assertIn("- Source File: `2026-04-01 12-55-07.wav`", rendered)
            self.assertIn("- Speakers: `1`", rendered)
            self.assertIn("- Language Hint: `ja,en`", rendered)
            self.assertNotIn("- Backend:", rendered)
            self.assertNotIn("- Status:", rendered)
            self.assertNotIn("Speaker Count Status", rendered)
            self.assertIn("## Turn 001", rendered)
            self.assertIn("Time: `00:00:12.340 - 00:00:15.980`", rendered)
            self.assertIn("IPA: `/konnitɕiwa hajimemaɕite/`", rendered)

    def test_render_ipa_writes_unavailable_note_when_turns_are_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "ipa" / "IPA.md"
            rendered = render_ipa(
                output_path=output_path,
                source_info={
                    "display_name": "2026-04-01 12-55-07.wav",
                    "language_hint": "ja",
                },
                backend_name="segment-ipa-passthrough",
                status="unavailable",
                speaker_count_status="unavailable",
                speaker_count_note="No speaker-attributed turns were available.",
                warnings=["IPA turn data is not available from the current transcription payload."],
                turns=[],
            )

            self.assertTrue(output_path.exists())
            self.assertNotIn("- Status:", rendered)
            self.assertNotIn("Speaker Count", rendered)
            self.assertNotIn("## Notes", rendered)
            self.assertIn("_No IPA turns generated._", rendered)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from timeline_for_audio_worker.artifacts import write_media_artifacts_index


class ArtifactsTests(unittest.TestCase):
    def test_write_media_artifacts_index_writes_primary_kind(self) -> None:
        with TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "media" / "sample-001"
            media_dir.mkdir(parents=True)

            payload = write_media_artifacts_index(
                media_dir=media_dir,
                media_id="sample-001",
                primary_artifact_kind="speaker_acoustic_units_timeline",
                artifacts=[
                    {
                        "kind": "speaker_acoustic_units_timeline",
                        "title": "Speaker Acoustic Units Timeline",
                        "display_name": "Speaker Acoustic Units Timeline",
                        "role": "primary",
                        "format": "json",
                        "relative_path": "timeline/speaker-acoustic-units-timeline.json",
                    }
                ],
            )

            self.assertEqual("speaker_acoustic_units_timeline", payload["primary_artifact_kind"])
            saved = json.loads((media_dir / "artifacts.json").read_text(encoding="utf-8"))
            self.assertEqual("sample-001", saved["media_id"])
            self.assertEqual("speaker_acoustic_units_timeline", saved["primary_artifact_kind"])


if __name__ == "__main__":
    unittest.main()

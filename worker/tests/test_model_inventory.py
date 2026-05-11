from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from timeline_for_audio_worker.model_inventory import (
    build_model_inventory,
    fetch_huggingface_model_metadata,
)


class ModelInventoryTests(unittest.TestCase):
    def test_build_model_inventory_lists_current_pipeline_models(self) -> None:
        payload = build_model_inventory(
            settings={"computeMode": "gpu"},
            include_remote=False,
        )

        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("gpu", payload["pipeline"]["compute_mode"])
        rows = {row["role"]: row for row in payload["models"]}
        self.assertEqual(
            "pyannote/speaker-diarization-community-1",
            rows["speaker_diarization"]["model_id"],
        )
        self.assertTrue(rows["speaker_diarization"]["requires_access_approval"])
        self.assertEqual(
            "Systran/faster-whisper-large-v3",
            rows["speech_transcription"]["model_id"],
        )
        self.assertEqual("local_tool", rows["speech_candidate_detection"]["source"])

    def test_fetch_huggingface_model_metadata_extracts_license(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            @staticmethod
            def read() -> bytes:
                return json.dumps(
                    {
                        "id": "owner/model",
                        "sha": "abc",
                        "gated": False,
                        "tags": ["license:apache-2.0"],
                        "cardData": {},
                    }
                ).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            payload = fetch_huggingface_model_metadata("owner/model")

        self.assertEqual("ok", payload["remote_status"])
        self.assertEqual("apache-2.0", payload["license"])
        self.assertEqual("tags", payload["license_source"])


if __name__ == "__main__":
    unittest.main()

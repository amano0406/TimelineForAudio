from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.settings import configured_path, init_settings, load_settings


class SettingsTests(unittest.TestCase):
    def test_init_settings_creates_settings_json_from_example(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            example_path = root / "settings.example.json"
            example_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "inputRoots": [
                            {
                                "id": "videos",
                                "displayName": "Videos",
                                "path": "C:\\Users\\amano\\Videos\\",
                                "enabled": True,
                            }
                        ],
                        "outputRoots": [
                            {
                                "id": "runs",
                                "displayName": "Runs",
                                "path": "C:\\Users\\amano\\video\\",
                                "enabled": True,
                            }
                        ],
                        "audioExtensions": [".mp3"],
                        "computeMode": "cpu",
                        "contextBuilderVersion": "context-builder-v2",
                        "ipaBackend": "sudachi-reading-ipa-v1",
                        "vadProfile": "default",
                        "uiLanguage": "ja",
                    }
                ),
                encoding="utf-8",
            )
            previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
            previous_example = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH")
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(settings_path)
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH"] = str(example_path)
            try:
                result = init_settings()
                second = init_settings()
                loaded = load_settings()
                settings_exists = settings_path.exists()
            finally:
                if previous_settings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings
                if previous_example is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH"] = previous_example

        self.assertTrue(result["created"])
        self.assertFalse(second["created"])
        self.assertTrue(settings_exists)
        self.assertEqual("ja", loaded["uiLanguage"])
        self.assertEqual("C:\\Users\\amano\\Videos\\", loaded["inputRoots"][0]["path"])

    def test_configured_path_maps_windows_drive_on_unix(self) -> None:
        path = configured_path("C:\\Users\\amano\\Videos\\")

        if os.name == "nt":
            self.assertEqual(Path("C:\\Users\\amano\\Videos\\"), path)
        else:
            self.assertEqual(Path("/mnt/c/Users/amano/Videos"), path)

    def test_configured_path_uses_explicit_docker_path_mapping(self) -> None:
        previous = os.environ.get("TIMELINE_FOR_AUDIO_PATH_MAPPINGS")
        os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = json.dumps(
            [
                {
                    "host": "C:\\Users\\amano\\Videos\\",
                    "container": "/host/input/videos",
                }
            ]
        )
        try:
            root_path = configured_path("C:\\Users\\amano\\Videos\\")
            child_path = configured_path("C:\\Users\\amano\\Videos\\sample\\a.mp3")
        finally:
            if previous is None:
                os.environ.pop("TIMELINE_FOR_AUDIO_PATH_MAPPINGS", None)
            else:
                os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = previous

        self.assertEqual(Path("/host/input/videos"), root_path)
        self.assertEqual(Path("/host/input/videos/sample/a.mp3"), child_path)


if __name__ == "__main__":
    unittest.main()

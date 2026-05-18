from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from timeline_for_audio_worker.settings import (
    configured_path,
    configured_path_to_host_text,
    ensure_runtime_settings,
    init_settings,
    load_settings,
    save_settings,
)


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
                            "C:\\Users\\amano\\Videos\\"
                        ],
                        "outputRoot": "C:\\Users\\amano\\video\\",
                        "huggingFaceToken": "",
                        "computeMode": "cpu",
                        "runtime": {
                            "instanceName": "",
                            "apiPort": 19100,
                        },
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
        self.assertEqual(
            {
                "schemaVersion",
                "inputRoots",
                "outputRoot",
                "huggingFaceToken",
                "computeMode",
                "runtime",
            },
            set(loaded),
        )
        self.assertEqual("C:\\Users\\amano\\Videos\\", loaded["inputRoots"][0])
        self.assertEqual(19100, loaded["runtime"]["apiPort"])

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

    def test_configured_path_to_host_text_reverses_explicit_mapping(self) -> None:
        previous = os.environ.get("TIMELINE_FOR_AUDIO_PATH_MAPPINGS")
        os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = json.dumps(
            [
                {
                    "host": "C:\\apps\\Timeline\\data",
                    "container": "/host/timeline-data",
                }
            ]
        )
        try:
            host_path = configured_path_to_host_text(
                "/host/timeline-data/work/downloads/audio/requested-items.zip"
            )
        finally:
            if previous is None:
                os.environ.pop("TIMELINE_FOR_AUDIO_PATH_MAPPINGS", None)
            else:
                os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = previous

        self.assertEqual(
            "C:\\apps\\Timeline\\data\\work\\downloads\\audio\\requested-items.zip",
            host_path,
        )

    def test_input_roots_can_be_saved_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "inputRoots": [
                            "C:\\Users\\amano\\Videos\\"
                        ],
                        "outputRoot": "",
                    }
                ),
                encoding="utf-8",
            )
            previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(settings_path)
            try:
                settings = load_settings()
                settings["inputRoots"] = [*settings["inputRoots"], "C:\\TimelineData\\Audio\\"]
                save_settings(settings)
                rows_after_add = load_settings()["inputRoots"]
                settings = load_settings()
                settings["inputRoots"] = [
                    row for row in settings["inputRoots"] if row != "C:\\TimelineData\\Audio\\"
                ]
                save_settings(settings)
                rows_after_remove = load_settings()["inputRoots"]
            finally:
                if previous_settings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings

        self.assertEqual(2, len(rows_after_add))
        self.assertEqual(["C:\\Users\\amano\\Videos\\"], rows_after_remove)

    def test_only_supported_settings_are_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "inputRoots": ["C:\\Users\\amano\\Videos\\"],
                        "outputRoot": "C:\\TimelineData\\audio",
                        "extraField": "not persisted",
                    }
                ),
                encoding="utf-8",
            )
            previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(settings_path)
            try:
                loaded = load_settings()
                save_settings(loaded)
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
            finally:
                if previous_settings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings

        expected_keys = {
            "schemaVersion",
            "inputRoots",
            "outputRoot",
            "huggingFaceToken",
            "computeMode",
            "runtime",
        }
        self.assertEqual(expected_keys, set(loaded))
        self.assertEqual(expected_keys, set(saved))
        self.assertEqual(19100, saved["runtime"]["apiPort"])

    def test_legacy_huggingface_token_is_read_and_saved_as_canonical_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "inputRoots": [],
                        "outputRoot": "",
                        "huggingfaceToken": "hf_legacy_value",
                        "computeMode": "cpu",
                    }
                ),
                encoding="utf-8",
            )
            previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(settings_path)
            try:
                loaded = load_settings()
                save_settings(loaded)
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
            finally:
                if previous_settings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings

        self.assertEqual("hf_legacy_value", loaded["huggingFaceToken"])
        self.assertEqual("hf_legacy_value", saved["huggingFaceToken"])
        self.assertNotIn("huggingfaceToken", saved)

    def test_ensure_runtime_settings_persists_instance_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "inputRoots": [],
                        "outputRoot": "",
                        "huggingFaceToken": "",
                        "computeMode": "cpu",
                        "runtime": {
                            "instanceName": "local-FF4E43E190",
                            "apiPort": 19100,
                        },
                    }
                ),
                encoding="utf-8",
            )
            previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(settings_path)
            try:
                runtime = ensure_runtime_settings()
                saved = json.loads(settings_path.read_text(encoding="utf-8"))
            finally:
                if previous_settings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings

        self.assertEqual("ff4e43e190", runtime["instanceName"])
        self.assertEqual("ff4e43e190", saved["runtime"]["instanceName"])
        self.assertEqual(19100, saved["runtime"]["apiPort"])


if __name__ == "__main__":
    unittest.main()

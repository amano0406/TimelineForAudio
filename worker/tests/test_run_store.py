from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from timeline_for_audio_worker.run_store import (
    build_items_archive,
    collect_input_items,
    create_run,
    create_refresh_run,
    generation_signature_for_settings,
    list_items,
    list_audio_file_rows,
    list_runs,
    remove_items,
    settings_snapshot,
)
from timeline_for_audio_worker.hashing import sha256_file
from timeline_for_audio_worker.settings import save_huggingface_token, save_settings


@contextmanager
def isolated_settings_environment(root: Path):
    previous_appdata = os.environ.get("TIMELINE_FOR_AUDIO_APPDATA_ROOT")
    previous_defaults = os.environ.get("TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS")
    previous_settings = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_PATH")
    previous_settings_example = os.environ.get("TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH")
    appdata_root = root / "app-data"
    appdata_root.mkdir(parents=True, exist_ok=True)
    defaults_path = root / "runtime.defaults.json"
    defaults_path.write_text("{}", encoding="utf-8")
    os.environ["TIMELINE_FOR_AUDIO_APPDATA_ROOT"] = str(appdata_root)
    os.environ["TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS"] = str(defaults_path)
    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = str(root / "settings.json")
    os.environ["TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH"] = str(root / "settings.example.json")
    try:
        yield
    finally:
        if previous_appdata is None:
            os.environ.pop("TIMELINE_FOR_AUDIO_APPDATA_ROOT", None)
        else:
            os.environ["TIMELINE_FOR_AUDIO_APPDATA_ROOT"] = previous_appdata
        if previous_defaults is None:
            os.environ.pop("TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS", None)
        else:
            os.environ["TIMELINE_FOR_AUDIO_RUNTIME_DEFAULTS"] = previous_defaults
        if previous_settings is None:
            os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_PATH", None)
        else:
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_PATH"] = previous_settings
        if previous_settings_example is None:
            os.environ.pop("TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH", None)
        else:
            os.environ["TIMELINE_FOR_AUDIO_SETTINGS_EXAMPLE_PATH"] = previous_settings_example


class RunStoreTests(unittest.TestCase):
    def test_collect_input_items_supports_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            source_dir.mkdir()
            file_a = source_dir / "a.wav"
            file_b = source_dir / "b.mp3"
            ignored = source_dir / "ignore.txt"
            file_a.write_bytes(b"a")
            file_b.write_bytes(b"b")
            ignored.write_text("x", encoding="utf-8")

            settings = {
                "audioExtensions": [".wav", ".mp3"],
                "inputRoots": [],
                "outputRoot": {"path": str(root / "runs")},
            }

            items = collect_input_items(settings=settings, files=[file_a], directories=[source_dir])

            self.assertEqual(2, len(items))
            self.assertEqual({"a.wav", "b.mp3"}, {item.display_name for item in items})

    def test_collect_input_items_maps_windows_paths_inside_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mapped_root = root / "mapped-output"
            sample_dir = mapped_root / "_validation-input"
            sample_dir.mkdir(parents=True)
            sample_file = sample_dir / "sample.mp3"
            sample_file.write_bytes(b"sample")
            previous_mappings = os.environ.get("TIMELINE_FOR_AUDIO_PATH_MAPPINGS")
            os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = json.dumps(
                [
                    {
                        "host": r"C:\Users\amano\video\\",
                        "container": str(mapped_root),
                    }
                ]
            )
            try:
                settings = {
                    "audioExtensions": [".mp3"],
                    "inputRoots": [],
                    "outputRoot": {"path": str(mapped_root)},
                }

                items = collect_input_items(
                    settings=settings,
                    files=[Path(r"C:\Users\amano\video\_validation-input\sample.mp3")],
                )
            finally:
                if previous_mappings is None:
                    os.environ.pop("TIMELINE_FOR_AUDIO_PATH_MAPPINGS", None)
                else:
                    os.environ["TIMELINE_FOR_AUDIO_PATH_MAPPINGS"] = previous_mappings

            self.assertEqual(1, len(items))
            self.assertEqual("sample.mp3", items[0].display_name)
            self.assertEqual(r"C:\Users\amano\video\_validation-input\sample.mp3", items[0].original_path)

    def test_create_refresh_run_uses_configured_input_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            (source_dir / "a.wav").write_bytes(b"a")
            (source_dir / "ignored.txt").write_text("x", encoding="utf-8")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
                "uiLanguage": "ja",
            }

            run_id, run_dir, summary = create_refresh_run(settings=settings)

            self.assertIsNotNone(run_id)
            self.assertIsNotNone(run_dir)
            self.assertEqual(1, summary["total_discovered"])
            self.assertEqual(1, summary["queued_count"])
            self.assertEqual(0, summary["skipped_count"])
            request = json.loads((Path(str(run_dir)) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual("speaker-acoustic-units-timeline", summary["artifact"])
            self.assertEqual("zipa-large-crctc-300k-onnx-v1", request["acoustic_unit_backend"])

    def test_create_refresh_run_skips_unchanged_catalog_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            audio_file = source_dir / "2026-04-01 12-00-00.wav"
            audio_file.write_bytes(b"stable-audio")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
                "uiLanguage": "ja",
            }
            signature = generation_signature_for_settings(
                settings=settings,
            )
            prior_media = runs_root / "run-prior" / "media" / "media-0001" / "timeline"
            prior_media.mkdir(parents=True)
            (prior_media / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[]}', encoding="utf-8"
            )
            catalog_dir = runs_root / ".timeline-for-audio"
            catalog_dir.mkdir(parents=True)
            (catalog_dir / "catalog.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": "run-prior",
                        "run_dir": str(runs_root / "run-prior"),
                        "audio_id": "media-0001",
                        "source_hash": sha256_file(audio_file),
                        "conversion_signature": signature,
                        "source_id": "meetings",
                        "source_relative_path": "2026-04-01 12-00-00.wav",
                        "source_file_identity": "meetings:2026-04-01 12-00-00.wav",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_id, run_dir, summary = create_refresh_run(
                settings=settings,
            )

            self.assertIsNone(run_id)
            self.assertIsNone(run_dir)
            self.assertEqual(1, summary["total_discovered"])
            self.assertEqual(0, summary["queued_count"])
            self.assertEqual(1, summary["skipped_count"])
            self.assertEqual("unchanged", summary["skipped"][0]["reason"])
            self.assertEqual(
                "meetings:2026-04-01 12-00-00.wav",
                summary["skipped"][0]["source_file_identity"],
            )

    def test_create_refresh_run_treats_renamed_same_hash_as_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            renamed_audio = source_dir / "renamed-meeting.wav"
            renamed_audio.write_bytes(b"stable-audio")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
                "uiLanguage": "ja",
            }
            signature = generation_signature_for_settings(
                settings=settings,
            )
            prior_media = runs_root / "run-prior" / "media" / "media-0001" / "timeline"
            prior_media.mkdir(parents=True)
            (prior_media / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[]}', encoding="utf-8"
            )
            catalog_dir = runs_root / ".timeline-for-audio"
            catalog_dir.mkdir(parents=True)
            (catalog_dir / "catalog.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": "run-prior",
                        "run_dir": str(runs_root / "run-prior"),
                        "audio_id": "media-0001",
                        "source_hash": sha256_file(renamed_audio),
                        "conversion_signature": signature,
                        "source_id": "meetings",
                        "source_relative_path": "original-meeting.wav",
                        "source_file_identity": "meetings:original-meeting.wav",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            run_id, run_dir, summary = create_refresh_run(
                settings=settings,
            )

            self.assertIsNotNone(run_id)
            self.assertIsNotNone(run_dir)
            self.assertEqual(1, summary["total_discovered"])
            self.assertEqual(1, summary["queued_count"])
            self.assertEqual(0, summary["skipped_count"])
            request = json.loads((Path(str(run_dir)) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "meetings:renamed-meeting.wav",
                request["input_items"][0]["source_file_identity"],
            )

    def test_remove_items_removes_catalog_row_and_media_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            target_audio = source_dir / "target.wav"
            other_audio = source_dir / "other.wav"
            target_audio.write_bytes(b"target-audio")
            other_audio.write_bytes(b"other-audio")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            target_media = runs_root / "run-prior" / "media" / "media-0001"
            other_media = runs_root / "run-prior" / "media" / "media-0002"
            (target_media / "timeline").mkdir(parents=True)
            (other_media / "timeline").mkdir(parents=True)
            (target_media / "timeline" / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[{"speaker":"SPEAKER_00"}]}',
                encoding="utf-8",
            )
            (other_media / "timeline" / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[]}',
                encoding="utf-8",
            )
            catalog_dir = runs_root / ".timeline-for-audio"
            catalog_dir.mkdir(parents=True)
            catalog_path = catalog_dir / "catalog.jsonl"
            catalog_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "run_id": "run-prior",
                                "run_dir": str(runs_root / "run-prior"),
                                "media_id": "media-0001",
                                "source_hash": sha256_file(target_audio),
                                "conversion_signature": signature,
                                "source_id": "meetings",
                                "source_relative_path": "target.wav",
                                "source_file_identity": "meetings:target.wav",
                            }
                        ),
                        json.dumps(
                            {
                                "run_id": "run-prior",
                                "run_dir": str(runs_root / "run-prior"),
                                "media_id": "media-0002",
                                "source_hash": sha256_file(other_audio),
                                "conversion_signature": signature,
                                "source_id": "meetings",
                                "source_relative_path": "other.wav",
                                "source_file_identity": "meetings:other.wav",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            items = list_items(settings=settings)
            target_item = next(
                item for item in items if item["source_file_identity"] == "meetings:target.wav"
            )

            payload = remove_items(
                item_ids=[str(target_item["item_id"])],
                settings=settings,
            )

            self.assertEqual(1, payload["catalog_rows_removed"])
            self.assertEqual(1, payload["media_dirs_removed"])
            self.assertEqual([target_item["item_id"]], payload["requested_item_ids"])
            self.assertFalse(target_media.exists())
            self.assertTrue(other_media.exists())
            self.assertTrue((runs_root / "run-prior").exists())
            remaining_catalog = catalog_path.read_text(encoding="utf-8")
            self.assertNotIn("meetings:target.wav", remaining_catalog)
            self.assertIn("meetings:other.wav", remaining_catalog)
            rows = list_audio_file_rows(settings=settings)
            status_by_name = {row["file_name"]: row["status"] for row in rows}
            self.assertEqual("unprocessed", status_by_name["target.wav"])
            self.assertEqual("completed", status_by_name["other.wav"])

    def test_remove_items_dry_run_does_not_remove_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            audio_file = source_dir / "target.wav"
            audio_file.write_bytes(b"target-audio")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            media_dir = runs_root / "run-prior" / "media" / "media-0001"
            (media_dir / "timeline").mkdir(parents=True)
            (media_dir / "timeline" / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[]}',
                encoding="utf-8",
            )
            catalog_dir = runs_root / ".timeline-for-audio"
            catalog_dir.mkdir(parents=True)
            catalog_path = catalog_dir / "catalog.jsonl"
            original_catalog = json.dumps(
                {
                    "run_id": "run-prior",
                    "run_dir": str(runs_root / "run-prior"),
                    "media_id": "media-0001",
                    "source_hash": sha256_file(audio_file),
                    "conversion_signature": signature,
                    "source_file_identity": "meetings:target.wav",
                }
            )
            catalog_path.write_text(original_catalog + "\n", encoding="utf-8")

            item_id = str(list_items(settings=settings)[0]["item_id"])

            payload = remove_items(
                item_ids=[item_id],
                settings=settings,
                dry_run=True,
            )

            self.assertTrue(payload["dry_run"])
            self.assertEqual(1, payload["catalog_rows_removed"])
            self.assertEqual(0, payload["media_dirs_removed"])
            self.assertTrue(media_dir.exists())
            self.assertEqual(original_catalog + "\n", catalog_path.read_text(encoding="utf-8"))

    def test_create_refresh_run_queues_all_items_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            for index in range(5):
                (source_dir / f"sample-{index}.wav").write_bytes(f"audio-{index}".encode())
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
            }

            run_id, run_dir, summary = create_refresh_run(settings=settings)

            self.assertIsNotNone(run_id)
            self.assertIsNotNone(run_dir)
            self.assertEqual(5, summary["total_discovered"])
            self.assertEqual(5, summary["queued_count"])
            self.assertEqual(0, summary["deferred_count"])
            self.assertIsNone(summary["queued_limit"])
            request = json.loads((Path(str(run_dir)) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(5, len(request["input_items"]))

    def test_create_refresh_run_limits_queued_items_with_explicit_max_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            for index in range(5):
                (source_dir / f"sample-{index}.wav").write_bytes(f"audio-{index}".encode())
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
            }

            run_id, run_dir, summary = create_refresh_run(settings=settings, max_items=2)

            self.assertIsNotNone(run_id)
            self.assertIsNotNone(run_dir)
            self.assertEqual(5, summary["total_discovered"])
            self.assertEqual(2, summary["queued_count"])
            self.assertEqual(3, summary["deferred_count"])
            self.assertEqual(2, summary["queued_limit"])
            self.assertEqual("batch_limit", summary["deferred"][0]["reason"])
            request = json.loads((Path(str(run_dir)) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(2, len(request["input_items"]))

    def test_create_run_writes_pending_contract_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            with isolated_settings_environment(root):
                settings = {
                    "audioExtensions": [".wav"],
                    "inputRoots": [],
                    "outputRoot": {"path": str(runs_root)},
                    "computeMode": "gpu",
                }
                save_settings(settings)
                save_huggingface_token("hf_test_value")

                source_file = root / "sample.wav"
                source_file.write_bytes(b"sample")
                items = collect_input_items(settings=settings, files=[source_file])
                run_id, run_dir = create_run(settings=settings, input_items=items)

                self.assertTrue((run_dir / "request.json").exists())
                self.assertTrue((run_dir / "status.json").exists())
                self.assertTrue((run_dir / "result.json").exists())
                request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
                self.assertEqual(run_id, request["run_id"])
                self.assertTrue(request["token_enabled"])
                self.assertEqual("gpu", request["compute_mode"])
                self.assertEqual("default", request["vad_profile"])
                self.assertEqual(request["conversion_signature"], request["generation_signature"])
                self.assertEqual("zipa-large-crctc-300k-onnx-v1", request["acoustic_unit_backend"])

    def test_list_runs_returns_created_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [],
                "outputRoot": {"path": str(runs_root)},
            }

            source_file = root / "sample.wav"
            source_file.write_bytes(b"sample")
            items = collect_input_items(settings=settings, files=[source_file])
            run_id, _ = create_run(settings=settings, input_items=items)

            rows = list_runs(settings)
            self.assertEqual(1, len(rows))
            self.assertEqual(run_id, rows[0]["run_id"])

    def test_create_run_allows_pending_runs_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [],
                "outputRoot": {"path": str(runs_root)},
            }

            first_file = root / "first.wav"
            second_file = root / "second.wav"
            first_file.write_bytes(b"first")
            second_file.write_bytes(b"second")

            first_items = collect_input_items(settings=settings, files=[first_file])
            second_items = collect_input_items(settings=settings, files=[second_file])

            first_run_id, _ = create_run(settings=settings, input_items=first_items)
            second_run_id, _ = create_run(settings=settings, input_items=second_items)

            rows = list_runs(settings)
            self.assertEqual(2, len(rows))
            self.assertEqual({first_run_id, second_run_id}, {row["run_id"] for row in rows})

    def test_settings_snapshot_reports_ready_when_token_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with isolated_settings_environment(root):
                source_dir = root / "audio"
                source_dir.mkdir()
                settings = {
                    "audioExtensions": [".wav"],
                    "inputRoots": [{"id": "meetings", "path": str(source_dir)}],
                    "outputRoot": {"path": str(root / "runs")},
                    "huggingfaceToken": "hf_test_value",
                }
                save_settings(settings)

                snapshot = settings_snapshot(settings)
                self.assertEqual("ready", snapshot["setup"]["state"])
                self.assertEqual([], snapshot["setup"]["blocking_reasons"])
                self.assertTrue(snapshot["token"]["configured"])
                self.assertEqual("cpu", snapshot["compute"]["mode"])

    def test_build_items_archive_uses_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            audio_file = source_dir / "target.wav"
            audio_file.write_bytes(b"target-audio")
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [
                    {
                        "id": "meetings",
                        "path": str(source_dir),
                    }
                ],
                "outputRoot": {"path": str(runs_root)},
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            media_dir = runs_root / "run-prior" / "media" / "media-0001"
            (media_dir / "timeline").mkdir(parents=True)
            (media_dir / "timeline" / "speaker-acoustic-units-timeline.json").write_text(
                '{"turns":[]}', encoding="utf-8"
            )
            (media_dir / "source").mkdir()
            (media_dir / "source" / "source-record.json").write_text(
                json.dumps(
                    {
                        "display_name": "20260324_125832.wav",
                        "original_path": str(audio_file),
                        "captured_at": "2026-03-24T12:58:32+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            catalog_dir = runs_root / ".timeline-for-audio"
            catalog_dir.mkdir(parents=True)
            (catalog_dir / "catalog.jsonl").write_text(
                json.dumps(
                    {
                        "run_id": "run-prior",
                        "run_dir": str(runs_root / "run-prior"),
                        "media_id": "media-0001",
                        "source_hash": sha256_file(audio_file),
                        "conversion_signature": signature,
                        "source_id": "meetings",
                        "source_relative_path": "target.wav",
                        "source_file_identity": "meetings:target.wav",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            item_id = str(list_items(settings=settings)[0]["item_id"])
            archive_path = build_items_archive(item_ids=[item_id], settings=settings)

            self.assertTrue(archive_path.exists())
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("README.html", names)
                self.assertIn("items.json", names)
                self.assertIn("items/2026-03-24 12-58-32.json", names)
                manifest = json.loads(archive.read("items.json").decode("utf-8"))
                self.assertEqual(item_id, manifest["items"][0]["item_id"])


if __name__ == "__main__":
    unittest.main()

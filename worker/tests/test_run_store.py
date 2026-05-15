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
    list_items_page,
    list_audio_file_page,
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


def write_master_item(
    master_root: Path,
    item_id: str,
    *,
    source_hash: str,
    conversion_signature: str,
    source_id: str = "meetings",
    source_relative_path: str,
    source_file_identity: str,
    file_name: str | None = None,
    generated_at: str = "2026-04-30T00:00:00+00:00",
    turns: list[dict[str, object]] | None = None,
) -> Path:
    item_dir = master_root / item_id
    item_dir.mkdir(parents=True)
    source = {
        "file_name": file_name or Path(source_relative_path).name,
        "display_name": file_name or Path(source_relative_path).name,
        "original_path": str(master_root / source_relative_path),
        "source_id": source_id,
        "source_relative_path": source_relative_path,
        "source_file_identity": source_file_identity,
        "source_hash": source_hash,
        "duration_sec": 10.0,
    }
    pipeline = {
        "pipeline_version": "test",
        "generation_signature": conversion_signature,
    }
    conversion = {
        "schema_version": 1,
        "artifact_type": "convert_info",
        "generated_at": generated_at,
        "source": source,
        "pipeline": pipeline,
    }
    timeline_turns = turns if turns is not None else []
    timeline = {
        "schema_version": 1,
        "artifact_type": "timeline",
        "source": source,
        "pipeline": pipeline,
        "turn_count": len(timeline_turns),
        "turns": timeline_turns,
    }
    (item_dir / "convert_info.json").write_text(
        json.dumps(conversion, ensure_ascii=False),
        encoding="utf-8",
    )
    (item_dir / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False),
        encoding="utf-8",
    )
    return item_dir


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
                "inputRoots": [],
                "outputRoot": str(root / "runs"),
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
                    "inputRoots": [],
                    "outputRoot": str(mapped_root),
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }

            run_id, run_dir, summary = create_refresh_run(settings=settings)

            self.assertIsNotNone(run_id)
            self.assertIsNotNone(run_dir)
            self.assertEqual(1, summary["total_discovered"])
            self.assertEqual(1, summary["queued_count"])
            self.assertEqual(0, summary["skipped_count"])
            request = json.loads((Path(str(run_dir)) / "request.json").read_text(encoding="utf-8"))
            self.assertEqual("timeline", summary["artifact"])
            self.assertEqual("faster-whisper-large-v3-v1", request["transcription_backend"])

    def test_create_refresh_run_skips_unchanged_catalog_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            audio_file = source_dir / "2026-04-01 12-00-00.wav"
            audio_file.write_bytes(b"stable-audio")
            settings = {
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(
                settings=settings,
            )
            write_master_item(
                runs_root,
                "media-0001",
                source_hash=sha256_file(audio_file),
                conversion_signature=signature,
                source_relative_path="2026-04-01 12-00-00.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::2026-04-01 12-00-00.wav",
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
                f"{source_dir}::2026-04-01 12-00-00.wav",
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(
                settings=settings,
            )
            write_master_item(
                runs_root,
                "media-0001",
                source_hash=sha256_file(renamed_audio),
                conversion_signature=signature,
                source_relative_path="original-meeting.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::original-meeting.wav",
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
                f"{source_dir}::renamed-meeting.wav",
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            target_media = write_master_item(
                runs_root,
                "media-0001",
                source_hash=sha256_file(target_audio),
                conversion_signature=signature,
                source_relative_path="target.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::target.wav",
                turns=[{"speaker": "SPEAKER_00"}],
            )
            other_media = write_master_item(
                runs_root,
                "media-0002",
                source_hash=sha256_file(other_audio),
                conversion_signature=signature,
                source_relative_path="other.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::other.wav",
            )

            items = list_items(settings=settings)
            target_item = next(
                item for item in items if item["source_file_identity"] == f"{source_dir}::target.wav"
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            media_dir = write_master_item(
                runs_root,
                "media-0001",
                source_hash=sha256_file(audio_file),
                conversion_signature=signature,
                source_relative_path="target.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::target.wav",
            )

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

    def test_files_list_prefers_available_item_over_stale_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with isolated_settings_environment(root):
                source_dir = root / "audio"
                master_root = root / "master"
                source_dir.mkdir()
                audio_file = source_dir / "target.wav"
                audio_file.write_bytes(b"target-audio")
                settings = {
                    "inputRoots": [str(source_dir)],
                    "outputRoot": str(master_root),
                    "computeMode": "cpu",
                }
                signature = generation_signature_for_settings(settings=settings)
                identity = f"{source_dir}::target.wav"
                write_master_item(
                    master_root,
                    "target-item",
                    source_hash=sha256_file(audio_file),
                    conversion_signature=signature,
                    source_relative_path="target.wav",
                    source_id=str(source_dir),
                    source_file_identity=identity,
                )
                input_items = collect_input_items(settings=settings, files=[audio_file])
                _, run_dir = create_run(settings=settings, input_items=input_items)
                status_path = Path(run_dir) / "status.json"
                manifest_path = Path(run_dir) / "manifest.json"
                status = json.loads(status_path.read_text(encoding="utf-8"))
                status["state"] = "failed"
                status_path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["items"] = [
                    {
                        "status": "failed",
                        "source_file_identity": identity,
                        "source_relative_path": "target.wav",
                        "duration_seconds": 1.0,
                    }
                ]
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

                rows = list_audio_file_rows(settings=settings)

            self.assertEqual("completed", rows[0]["status"])
            self.assertEqual("target-item", rows[0]["media_id"])

    def test_list_items_returns_latest_first_and_paginates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master_root = root / "master"
            settings = {
                "inputRoots": [str(root / "audio")],
                "outputRoot": str(master_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            rows = [
                ("media-old", "old.wav", 1_700_000_000),
                ("media-new", "new.wav", 1_700_000_200),
                ("media-mid", "mid.wav", 1_700_000_100),
            ]
            for item_id, file_name, mtime in rows:
                item_dir = write_master_item(
                    master_root,
                    item_id,
                    source_hash=f"sha-{item_id}",
                    conversion_signature=signature,
                    source_relative_path=file_name,
                    source_id=str(root / "audio"),
                    source_file_identity=f"{root / 'audio'}::{file_name}",
                    file_name=file_name,
                )
                os.utime(item_dir / "convert_info.json", (mtime, mtime))
                os.utime(item_dir / "timeline.json", (mtime, mtime))
                os.utime(item_dir, (mtime, mtime))

            all_items = list_items(settings=settings)
            self.assertEqual(
                ["media-new", "media-mid", "media-old"],
                [str(row["item_id"]) for row in all_items],
            )

            first_page = list_items_page(settings=settings, page=1, page_size=2)
            self.assertEqual(
                ["media-new", "media-mid"],
                [str(row["item_id"]) for row in first_page["items"]],
            )
            self.assertEqual(3, first_page["item_count"])
            self.assertEqual(3, first_page["total_items"])
            self.assertEqual(
                {"order": "desc", "fields": ["updated_at", "created_at", "item_id"]},
                first_page["sort"],
            )
            self.assertEqual(
                {
                    "mode": "page",
                    "page": 1,
                    "page_size": 2,
                    "total_items": 3,
                    "total_pages": 2,
                    "returned_items": 2,
                    "offset": 0,
                    "range_start": 1,
                    "range_end": 2,
                    "has_previous": False,
                    "has_next": True,
                },
                first_page["pagination"],
            )
            second_page = list_items_page(settings=settings, page=2, page_size=2)
            self.assertEqual(["media-old"], [str(row["item_id"]) for row in second_page["items"]])
            self.assertFalse(second_page["pagination"]["has_next"])
            all_page = list_items_page(settings=settings)
            self.assertEqual("all", all_page["pagination"]["mode"])
            self.assertEqual(3, all_page["pagination"]["returned_items"])
            self.assertEqual(["media-new", "media-mid", "media-old"], [row["item_id"] for row in all_page["items"]])

    def test_list_audio_files_returns_latest_first_and_paginates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            master_root = root / "master"
            source_dir.mkdir()
            files = [
                ("old.wav", 1_700_000_000),
                ("new.wav", 1_700_000_200),
                ("mid.wav", 1_700_000_100),
            ]
            for file_name, mtime in files:
                path = source_dir / file_name
                path.write_bytes(file_name.encode())
                os.utime(path, (mtime, mtime))
            settings = {
                "inputRoots": [str(source_dir)],
                "outputRoot": str(master_root),
                "computeMode": "cpu",
            }

            all_files = list_audio_file_rows(settings=settings)
            self.assertEqual(["new.wav", "mid.wav", "old.wav"], [row["file_name"] for row in all_files])

            first_page = list_audio_file_page(settings=settings, page=1, page_size=2)
            self.assertEqual(["new.wav", "mid.wav"], [row["file_name"] for row in first_page["files"]])
            self.assertEqual(3, first_page["file_count"])
            self.assertEqual(3, first_page["total_files"])
            self.assertEqual(
                {"order": "desc", "fields": ["modified_at", "source_file_identity"]},
                first_page["sort"],
            )
            self.assertEqual(
                {
                    "mode": "page",
                    "page": 1,
                    "page_size": 2,
                    "total_files": 3,
                    "total_pages": 2,
                    "returned_files": 2,
                    "offset": 0,
                    "range_start": 1,
                    "range_end": 2,
                    "has_previous": False,
                    "has_next": True,
                },
                first_page["pagination"],
            )
            second_page = list_audio_file_page(settings=settings, page=2, page_size=2)
            self.assertEqual(["old.wav"], [row["file_name"] for row in second_page["files"]])
            self.assertFalse(second_page["pagination"]["has_next"])
            all_page = list_audio_file_page(settings=settings)
            self.assertEqual("all", all_page["pagination"]["mode"])
            self.assertEqual(3, all_page["pagination"]["returned_files"])
            self.assertEqual(["new.wav", "mid.wav", "old.wav"], [row["file_name"] for row in all_page["files"]])

    def test_create_refresh_run_queues_all_items_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "audio"
            runs_root = root / "runs"
            source_dir.mkdir()
            for index in range(5):
                (source_dir / f"sample-{index}.wav").write_bytes(f"audio-{index}".encode())
            settings = {
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
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
                    "inputRoots": [],
                    "outputRoot": str(runs_root),
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
                self.assertEqual("faster-whisper-large-v3-v1", request["transcription_backend"])

    def test_list_runs_returns_created_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "inputRoots": [],
                "outputRoot": str(runs_root),
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
                "inputRoots": [],
                "outputRoot": str(runs_root),
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
                    "inputRoots": [str(source_dir)],
                    "outputRoot": str(root / "runs"),
                    "huggingFaceToken": "hf_test_value",
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
                "inputRoots": [str(source_dir)],
                "outputRoot": str(runs_root),
                "computeMode": "cpu",
            }
            signature = generation_signature_for_settings(settings=settings)
            write_master_item(
                runs_root,
                "media-0001",
                source_hash=sha256_file(audio_file),
                conversion_signature=signature,
                source_relative_path="target.wav",
                source_id=str(source_dir),
                source_file_identity=f"{source_dir}::target.wav",
                file_name="20260324_125832.wav",
            )

            item_id = str(list_items(settings=settings)[0]["item_id"])
            archive_path = build_items_archive(item_ids=[item_id], settings=settings)

            self.assertTrue(archive_path.exists())
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("README.md", names)
                self.assertIn("items/media-0001/convert_info.json", names)
                self.assertIn("items/media-0001/timeline.json", names)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from audio2timeline_worker.job_store import (
    build_run_archive,
    collect_input_items,
    create_job,
    list_runs,
    settings_snapshot,
)
from audio2timeline_worker.settings import save_huggingface_token, save_settings


@contextmanager
def isolated_settings_environment(root: Path):
    previous_appdata = os.environ.get("AUDIO2TIMELINE_APPDATA_ROOT")
    previous_defaults = os.environ.get("AUDIO2TIMELINE_RUNTIME_DEFAULTS")
    appdata_root = root / "app-data"
    appdata_root.mkdir(parents=True, exist_ok=True)
    (appdata_root / "secrets").mkdir(parents=True, exist_ok=True)
    defaults_path = root / "runtime.defaults.json"
    defaults_path.write_text("{}", encoding="utf-8")
    os.environ["AUDIO2TIMELINE_APPDATA_ROOT"] = str(appdata_root)
    os.environ["AUDIO2TIMELINE_RUNTIME_DEFAULTS"] = str(defaults_path)
    try:
        yield
    finally:
        if previous_appdata is None:
            os.environ.pop("AUDIO2TIMELINE_APPDATA_ROOT", None)
        else:
            os.environ["AUDIO2TIMELINE_APPDATA_ROOT"] = previous_appdata
        if previous_defaults is None:
            os.environ.pop("AUDIO2TIMELINE_RUNTIME_DEFAULTS", None)
        else:
            os.environ["AUDIO2TIMELINE_RUNTIME_DEFAULTS"] = previous_defaults


class JobStoreTests(unittest.TestCase):
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
                "outputRoots": [{"id": "runs", "path": str(root / "runs"), "enabled": True}],
                "huggingfaceTermsConfirmed": False,
            }

            items = collect_input_items(settings=settings, files=[file_a], directories=[source_dir])

            self.assertEqual(2, len(items))
            self.assertEqual({"a.wav", "b.mp3"}, {item.display_name for item in items})

    def test_create_job_writes_pending_contract_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            with isolated_settings_environment(root):
                settings = {
                    "audioExtensions": [".wav"],
                    "inputRoots": [],
                    "outputRoots": [{"id": "runs", "path": str(runs_root), "enabled": True}],
                    "huggingfaceTermsConfirmed": True,
                    "computeMode": "gpu",
                    "processingQuality": "high",
                }
                save_settings(settings)
                save_huggingface_token("hf_test_value")

                source_file = root / "sample.wav"
                source_file.write_bytes(b"sample")
                items = collect_input_items(settings=settings, files=[source_file])
                job_id, run_dir = create_job(settings=settings, input_items=items)

                self.assertTrue((run_dir / "request.json").exists())
                self.assertTrue((run_dir / "status.json").exists())
                self.assertTrue((run_dir / "result.json").exists())
                request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
                self.assertEqual(job_id, request["job_id"])
                self.assertTrue(request["token_enabled"])
                self.assertEqual("gpu", request["compute_mode"])
                self.assertEqual("high", request["processing_quality"])

    def test_list_runs_returns_created_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [],
                "outputRoots": [{"id": "runs", "path": str(runs_root), "enabled": True}],
                "huggingfaceTermsConfirmed": False,
            }

            source_file = root / "sample.wav"
            source_file.write_bytes(b"sample")
            items = collect_input_items(settings=settings, files=[source_file])
            job_id, _ = create_job(settings=settings, input_items=items)

            rows = list_runs(settings)
            self.assertEqual(1, len(rows))
            self.assertEqual(job_id, rows[0]["job_id"])

    def test_create_job_allows_pending_jobs_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [],
                "outputRoots": [{"id": "runs", "path": str(runs_root), "enabled": True}],
                "huggingfaceTermsConfirmed": False,
            }

            first_file = root / "first.wav"
            second_file = root / "second.wav"
            first_file.write_bytes(b"first")
            second_file.write_bytes(b"second")

            first_items = collect_input_items(settings=settings, files=[first_file])
            second_items = collect_input_items(settings=settings, files=[second_file])

            first_job_id, _ = create_job(settings=settings, input_items=first_items)
            second_job_id, _ = create_job(settings=settings, input_items=second_items)

            rows = list_runs(settings)
            self.assertEqual(2, len(rows))
            self.assertEqual({first_job_id, second_job_id}, {row["job_id"] for row in rows})

    def test_settings_snapshot_reports_ready_when_token_and_terms_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with isolated_settings_environment(root):
                settings = {
                    "audioExtensions": [".wav"],
                    "inputRoots": [],
                    "outputRoots": [{"id": "runs", "path": str(root / "runs"), "enabled": True}],
                    "huggingfaceTermsConfirmed": True,
                }
                save_settings(settings)
                save_huggingface_token("hf_test_value")

                snapshot = settings_snapshot(settings)
                self.assertTrue(snapshot["has_token"])
                self.assertTrue(snapshot["terms_confirmed"])
                self.assertTrue(snapshot["ready"])

    def test_build_run_archive_creates_zip_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runs_root = root / "runs"
            settings = {
                "audioExtensions": [".wav"],
                "inputRoots": [],
                "outputRoots": [{"id": "runs", "path": str(runs_root), "enabled": True}],
                "huggingfaceTermsConfirmed": False,
            }

            source_file = root / "sample.wav"
            source_file.write_bytes(b"sample")
            items = collect_input_items(settings=settings, files=[source_file])
            job_id, run_dir = create_job(settings=settings, input_items=items)
            (run_dir / "result.json").write_text(
                json.dumps({"job_id": job_id, "state": "completed"}, ensure_ascii=False),
                encoding="utf-8",
            )
            media_dir = run_dir / "media" / "sample-12345678"
            (media_dir / "timeline").mkdir(parents=True)
            (media_dir / "timeline" / "timeline.md").write_text("# Timeline\n", encoding="utf-8")
            (media_dir / "source.json").write_text(
                json.dumps(
                    {
                        "display_name": "20260324_125832.wav",
                        "original_path": str(source_file),
                        "captured_at": "2026-03-24T12:58:32+09:00",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "TRANSCRIPTION_INFO.md").write_text(
                "# Transcription Info\n", encoding="utf-8"
            )

            archive_path = build_run_archive(job_id, settings=settings)

            self.assertTrue(archive_path.exists())
            self.assertEqual(".zip", archive_path.suffix)
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
                self.assertIn("README.md", names)
                self.assertIn("TRANSCRIPTION_INFO.md", names)
                self.assertIn("timelines/2026-03-24 12-58-32.md", names)


if __name__ == "__main__":
    unittest.main()

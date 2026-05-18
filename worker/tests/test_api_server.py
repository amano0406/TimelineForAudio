from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from timeline_for_audio_worker import api_server


class ApiServerTests(unittest.TestCase):
    def test_api_server_dispatches_items_refresh_without_process_spawn(self) -> None:
        summary = {
            "total_discovered": 1,
            "queued_count": 1,
            "skipped_count": 0,
            "deferred_count": 0,
            "queued_limit": None,
            "queued": [{"file_name": "sample.wav"}],
            "skipped": [],
            "deferred": [],
        }
        with (
            patch.object(api_server, "load_settings", return_value={"computeMode": "cpu"}),
            patch.object(
                api_server,
                "create_refresh_run",
                return_value=("run-1", Path("/tmp/run-1"), summary),
            ) as create_run,
        ):
            status, payload = api_server.handle_request("POST", "/items/refresh", {"queueOnly": True})

        self.assertEqual(200, status)
        create_run.assert_called_once_with(
            settings={"computeMode": "cpu"},
            source_ids=[],
            output_root_id="master",
            reprocess_duplicates=False,
            max_items=None,
        )
        self.assertEqual("pending", payload["state"])
        self.assertEqual("run-1", payload["run_id"])
        self.assertTrue(payload["queue_only"])

    def test_api_server_starts_refresh_job(self) -> None:
        summary = {
            "total_discovered": 1,
            "queued_count": 1,
            "skipped_count": 0,
            "deferred_count": 0,
            "queued_limit": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-1"
            run_dir.mkdir()
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "state": "pending",
                        "current_stage": "queued",
                        "message": "Queued for worker pickup.",
                        "items_total": 1,
                        "progress_percent": 0.0,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "result.json").write_text(
                json.dumps({"run_id": "run-1", "state": "pending"}),
                encoding="utf-8",
            )
            with (
                patch.object(api_server, "load_settings", return_value={"computeMode": "cpu"}),
                patch.object(api_server, "get_active_run", return_value=None),
                patch.object(api_server, "create_refresh_run", return_value=("run-1", run_dir, summary)),
                patch.object(api_server, "find_run_dir", return_value=run_dir),
            ):
                status, payload = api_server.handle_request("POST", "/jobs", {"type": "refresh"})

        self.assertEqual(200, status)
        self.assertEqual("timeline.product_job.v1", payload["schemaVersion"])
        self.assertEqual("audio", payload["productId"])
        self.assertEqual("run-1", payload["jobId"])
        self.assertEqual("queued", payload["state"])
        self.assertEqual(1, payload["progress"]["total"])

    def test_api_server_dispatches_item_download_without_process_spawn(self) -> None:
        with (
            patch.object(
                api_server,
                "list_items",
                return_value=[
                    {"item_id": "item-a", "status": "available"},
                    {"item_id": "item-b", "status": "missing_artifact"},
                ],
            ),
            patch.object(api_server, "configured_path", side_effect=lambda value: Path(f"/mapped/{value}")) as map_path,
            patch.object(api_server, "configured_path_to_host_text", return_value="all-items.zip") as to_host_text,
            patch.object(api_server, "build_items_archive", return_value=Path("/mapped/all-items.zip")) as build_archive,
        ):
            status, payload = api_server.handle_request("POST", "/items/download", {})

        self.assertEqual(200, status)
        map_path.assert_not_called()
        to_host_text.assert_called_once_with(Path("/mapped/all-items.zip"))
        build_archive.assert_called_once_with(item_ids=["item-a"], output=None)
        self.assertEqual({"archive_path": "all-items.zip", "item_ids": ["item-a"]}, payload)

    def test_api_server_maps_explicit_download_output_path(self) -> None:
        with (
            patch.object(
                api_server,
                "list_items",
                return_value=[{"item_id": "item-a", "status": "available"}],
            ),
            patch.object(api_server, "configured_path", return_value=Path("/host/timeline-data/work/requested.zip")) as map_path,
            patch.object(api_server, "configured_path_to_host_text", return_value=r"C:\apps\Timeline\data\work\requested.zip") as to_host_text,
            patch.object(api_server, "build_items_archive", return_value=Path("/host/timeline-data/work/requested.zip")) as build_archive,
        ):
            status, payload = api_server.handle_request(
                "POST",
                "/items/download",
                {"outputPath": r"C:\apps\Timeline\data\work\requested.zip"},
            )

        self.assertEqual(200, status)
        map_path.assert_called_once_with(r"C:\apps\Timeline\data\work\requested.zip")
        build_archive.assert_called_once_with(
            item_ids=["item-a"],
            output=Path("/host/timeline-data/work/requested.zip"),
        )
        to_host_text.assert_called_once_with(Path("/host/timeline-data/work/requested.zip"))
        self.assertEqual(r"C:\apps\Timeline\data\work\requested.zip", payload["archive_path"])

    def test_api_server_returns_machine_readable_errors(self) -> None:
        with patch.object(api_server, "list_items", return_value=[]):
            status, payload = api_server.handle_request("POST", "/items/download", {})

        self.assertEqual(500, status)
        self.assertFalse(payload["ok"])
        self.assertEqual("ValueError", payload["error"]["type"])
        self.assertIn("At least one available item id", payload["error"]["message"])

    def test_settings_status_json_contract(self) -> None:
        expected = {
            "setup": {"state": "ready", "blocking_reasons": []},
            "token": {"configured": True, "preview": "hf_test"},
            "compute": {"mode": "gpu"},
            "inputs": [r"C:\TimelineData\audio"],
            "master": r"C:\TimelineData\audio",
        }
        with patch.object(api_server, "settings_snapshot", return_value=expected):
            status, payload = api_server.handle_request("POST", "/settings/status", {})

        self.assertEqual(200, status)
        self.assertEqual(expected, payload)

    def test_files_list_json_contract(self) -> None:
        expected = {
            "file_count": 1,
            "total_files": 1,
            "pagination": {
                "mode": "all",
                "page": None,
                "page_size": None,
                "total_files": 1,
                "total_pages": 1,
                "returned_files": 1,
                "offset": 0,
                "range_start": 1,
                "range_end": 1,
                "has_previous": False,
                "has_next": False,
            },
            "sort": {"order": "desc", "fields": ["modified_at", "source_file_identity"]},
            "files": [{"file_name": "sample.wav", "status": "unprocessed"}],
        }
        with patch.object(api_server, "list_audio_file_page", return_value=expected) as list_page:
            status, payload = api_server.handle_request("POST", "/files/list", {})

        self.assertEqual(200, status)
        list_page.assert_called_once_with(include_probe=False, page=None, page_size=None)
        self.assertEqual(expected, json.loads(json.dumps(payload)))


if __name__ == "__main__":
    unittest.main()

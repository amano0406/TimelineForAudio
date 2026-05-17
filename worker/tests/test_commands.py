from __future__ import annotations

from contextlib import redirect_stderr
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from timeline_for_audio_worker import commands as command_module


class CommandTests(unittest.TestCase):
    def test_settings_status_json_contract(self) -> None:
        payload = {
            "setup": {"state": "ready", "blocking_reasons": []},
            "token": {"configured": True, "preview": "hf_t窶｢窶｢窶｢窶｢alue"},
            "compute": {"mode": "gpu"},
            "inputs": [r"C:\TimelineData\audio"],
            "master": r"C:\TimelineData\audio",
        }
        stdout = StringIO()
        with (
            patch.object(command_module, "settings_snapshot", return_value=payload),
            redirect_stdout(stdout),
        ):
            exit_code = command_module.cmd_settings_status(as_json=True)

        self.assertEqual(0, exit_code)
        self.assertEqual(payload, json.loads(stdout.getvalue()))

    def test_files_list_json_contract(self) -> None:
        payload = {
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
        stdout = StringIO()
        with (
            patch.object(command_module, "list_audio_file_page", return_value=payload) as list_page,
            redirect_stdout(stdout),
        ):
            exit_code = command_module.cmd_files_list(
                include_probe=False,
                page=None,
                page_size=None,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        list_page.assert_called_once_with(include_probe=False, page=None, page_size=None)
        self.assertEqual(payload, json.loads(stdout.getvalue()))

    def test_items_list_json_contract(self) -> None:
        payload = {
            "item_count": 1,
            "total_items": 1,
            "pagination": {
                "mode": "all",
                "page": None,
                "page_size": None,
                "total_items": 1,
                "total_pages": 1,
                "returned_items": 1,
                "offset": 0,
                "range_start": 1,
                "range_end": 1,
                "has_previous": False,
                "has_next": False,
            },
            "sort": {"order": "desc", "fields": ["updated_at", "created_at", "item_id"]},
            "items": [{"item_id": "item-a", "status": "available"}],
        }
        stdout = StringIO()
        with (
            patch.object(command_module, "list_items_page", return_value=payload) as list_page,
            redirect_stdout(stdout),
        ):
            exit_code = command_module.cmd_items_list(page=None, page_size=None, as_json=True)

        self.assertEqual(0, exit_code)
        list_page.assert_called_once_with(page=None, page_size=None)
        self.assertEqual(payload, json.loads(stdout.getvalue()))

    def test_items_refresh_queue_only_json_contract(self) -> None:
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
        stdout = StringIO()
        with (
            patch.object(command_module, "load_settings", return_value={"computeMode": "cpu"}),
            patch.object(
                command_module,
                "create_refresh_run",
                return_value=("run-1", Path("/tmp/run-1"), summary),
            ) as create_run,
            redirect_stdout(stdout),
        ):
            exit_code = command_module.cmd_items_refresh(
                source_ids=[],
                output_root_id=None,
                reprocess_duplicates=False,
                max_items=None,
                queue_only=True,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        create_run.assert_called_once_with(
            settings={"computeMode": "cpu"},
            source_ids=[],
            output_root_id=None,
            reprocess_duplicates=False,
            max_items=None,
        )
        payload = json.loads(stdout.getvalue())
        self.assertEqual("pending", payload["state"])
        self.assertEqual("run-1", payload["run_id"])
        self.assertEqual(str(Path("/tmp/run-1")), payload["run_dir"])
        self.assertEqual("timeline", payload["artifact"])
        self.assertTrue(payload["queue_only"])
        self.assertEqual(1, payload["total_discovered"])

    def test_settings_validate_token_is_not_public_command(self) -> None:
        with patch.object(sys, "argv", ["timeline-for-audio", "settings", "validate-token"]):
            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    command_module.parse_args()

    def test_items_download_defaults_to_available_item_ids(self) -> None:
        with (
            patch.object(
                command_module,
                "list_items",
                return_value=[
                    {"item_id": "item-a", "status": "available"},
                    {"item_id": "item-b", "status": "missing_artifact"},
                    {"item_id": "item-c", "status": "available"},
                ],
            ),
            patch.object(command_module, "build_items_archive", return_value=Path("all-items.zip")) as build_archive,
            patch.object(command_module, "_print_payload"),
        ):
            exit_code = command_module.cmd_items_download(
                item_id_value=None,
                output=None,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        build_archive.assert_called_once_with(
            item_ids=["item-a", "item-c"],
            output=None,
        )

    def test_items_download_defaults_to_all_when_item_id_is_omitted(self) -> None:
        stdout = StringIO()
        with (
            patch.object(
                command_module,
                "list_items",
                return_value=[
                    {"item_id": "item-a", "status": "available"},
                    {"item_id": "item-b", "status": "available"},
                ],
            ),
            patch.object(command_module, "build_items_archive", return_value=Path("all-items.zip")) as build_archive,
            redirect_stdout(stdout),
        ):
            exit_code = command_module.cmd_items_download(
                item_id_value=None,
                output=None,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        build_archive.assert_called_once_with(
            item_ids=["item-a", "item-b"],
            output=None,
        )
        self.assertEqual(
            {"archive_path": "all-items.zip", "item_ids": ["item-a", "item-b"]},
            json.loads(stdout.getvalue()),
        )

    def test_items_download_requires_at_least_one_available_item(self) -> None:
        with patch.object(command_module, "list_items", return_value=[]):
            with self.assertRaisesRegex(ValueError, "At least one available item id"):
                command_module.cmd_items_download(
                    item_id_value=None,
                    output=None,
                    as_json=True,
                )

    def test_items_download_rejects_empty_explicit_item_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one available item id"):
            command_module.cmd_items_download(
                item_id_value=",",
                output=None,
                as_json=True,
            )

    def test_json_command_errors_are_machine_readable(self) -> None:
        stdout = StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["timeline-for-audio", "items", "download", "--json"],
            ),
            patch.object(command_module, "assert_worker_runtime_allowed"),
            patch.object(command_module, "list_items", return_value=[]),
            redirect_stdout(stdout),
        ):
            exit_code = command_module.run()

        self.assertEqual(1, exit_code)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual("ValueError", payload["error"]["type"])
        self.assertIn("At least one available item id", payload["error"]["message"])

    def test_text_command_errors_do_not_print_traceback(self) -> None:
        stdout = StringIO()
        stderr = StringIO()
        with (
            patch.object(sys, "argv", ["timeline-for-audio", "items", "download"]),
            patch.object(command_module, "assert_worker_runtime_allowed"),
            patch.object(command_module, "list_items", return_value=[]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = command_module.run()

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("At least one available item id", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()


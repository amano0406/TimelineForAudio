from __future__ import annotations

from contextlib import redirect_stderr
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from timeline_for_audio_worker import cli


class CliTests(unittest.TestCase):
    def test_settings_validate_token_is_not_public_cli(self) -> None:
        with patch.object(sys, "argv", ["timeline-for-audio", "settings", "validate-token"]):
            with redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    cli.parse_args()

    def test_items_download_defaults_to_available_item_ids(self) -> None:
        with (
            patch.object(
                cli,
                "list_items",
                return_value=[
                    {"item_id": "item-a", "status": "available"},
                    {"item_id": "item-b", "status": "missing_artifact"},
                    {"item_id": "item-c", "status": "available"},
                ],
            ),
            patch.object(cli, "build_items_archive", return_value=Path("all-items.zip")) as build_archive,
            patch.object(cli, "_print_payload"),
        ):
            exit_code = cli.cmd_items_download(
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
        with (
            patch.object(
                cli,
                "list_items",
                return_value=[
                    {"item_id": "item-a", "status": "available"},
                    {"item_id": "item-b", "status": "available"},
                ],
            ),
            patch.object(cli, "build_items_archive", return_value=Path("all-items.zip")) as build_archive,
            patch.object(cli, "_print_payload"),
        ):
            exit_code = cli.cmd_items_download(
                item_id_value=None,
                output=None,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        build_archive.assert_called_once_with(
            item_ids=["item-a", "item-b"],
            output=None,
        )

    def test_items_download_requires_at_least_one_available_item(self) -> None:
        with patch.object(cli, "list_items", return_value=[]):
            with self.assertRaisesRegex(ValueError, "At least one available item id"):
                cli.cmd_items_download(
                    item_id_value=None,
                    output=None,
                    as_json=True,
                )

    def test_items_download_rejects_empty_explicit_item_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one available item id"):
            cli.cmd_items_download(
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
            patch.object(cli, "assert_cli_runtime_allowed"),
            patch.object(cli, "list_items", return_value=[]),
            redirect_stdout(stdout),
        ):
            exit_code = cli.run()

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
            patch.object(cli, "assert_cli_runtime_allowed"),
            patch.object(cli, "list_items", return_value=[]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = cli.run()

        self.assertEqual(1, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("At least one available item id", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

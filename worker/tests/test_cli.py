from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
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


if __name__ == "__main__":
    unittest.main()

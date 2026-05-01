from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from timeline_for_audio_worker import cli


class CliTests(unittest.TestCase):
    def test_items_download_all_uses_available_item_ids(self) -> None:
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
                include_all=True,
                output=None,
                as_json=True,
            )

        self.assertEqual(0, exit_code)
        build_archive.assert_called_once_with(
            item_ids=["item-a", "item-c"],
            output=None,
        )

    def test_items_download_rejects_all_with_explicit_item_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "Use either --all or --item-id"):
            cli.cmd_items_download(
                item_id_value="item-a",
                include_all=True,
                output=None,
                as_json=True,
            )

    def test_items_download_requires_at_least_one_item(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one available item id"):
            cli.cmd_items_download(
                item_id_value=None,
                include_all=False,
                output=None,
                as_json=True,
            )


if __name__ == "__main__":
    unittest.main()

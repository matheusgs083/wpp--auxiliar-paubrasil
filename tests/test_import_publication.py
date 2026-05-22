from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.services.import_publication import resolve_effective_import_batch_id


class ImportPublicationTests(unittest.TestCase):
    def test_resolve_prefers_active_batch(self) -> None:
        conn = SimpleNamespace()

        with (
            patch("bot_api.services.import_publication.get_active_import_batch_id", return_value=7) as active_mock,
            patch("bot_api.services.import_publication.get_latest_import_batch_id") as latest_mock,
        ):
            batch_id = resolve_effective_import_batch_id(conn, "reports", "dclientes")

        self.assertEqual(batch_id, 7)
        active_mock.assert_called_once_with(conn, "reports", "dclientes")
        latest_mock.assert_not_called()

    def test_resolve_can_activate_latest_batch_when_missing(self) -> None:
        conn = SimpleNamespace()

        with (
            patch("bot_api.services.import_publication.get_active_import_batch_id", return_value=None),
            patch("bot_api.services.import_publication.get_latest_import_batch_id", return_value=12) as latest_mock,
            patch("bot_api.services.import_publication.activate_import_batch") as activate_mock,
        ):
            batch_id = resolve_effective_import_batch_id(
                conn,
                "reports",
                "inadimplencia",
                activate_if_missing=True,
            )

        self.assertEqual(batch_id, 12)
        latest_mock.assert_called_once_with(conn, "reports", "inadimplencia")
        activate_mock.assert_called_once_with(conn, "reports", "inadimplencia", 12)

    def test_resolve_returns_none_when_dataset_has_no_batches(self) -> None:
        conn = SimpleNamespace()

        with (
            patch("bot_api.services.import_publication.get_active_import_batch_id", return_value=None),
            patch("bot_api.services.import_publication.get_latest_import_batch_id", return_value=None),
            patch("bot_api.services.import_publication.activate_import_batch") as activate_mock,
        ):
            batch_id = resolve_effective_import_batch_id(
                conn,
                "reports",
                "giro",
                activate_if_missing=True,
            )

        self.assertIsNone(batch_id)
        activate_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()

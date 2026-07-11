"""自選清單 SQLite CRUD 單元測試。"""

import tempfile
import unittest
from pathlib import Path

from src.data_loader import StockDataManager


class TestWatchlistSystem(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.manager = StockDataManager(
            db_path=Path(self.temp_directory.name) / "test_stock_system.db"
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp_directory.cleanup()

    def test_watchlist_create_add_read_remove_and_delete(self) -> None:
        list_id = self.manager.create_watchlist("半導體")
        self.assertGreater(list_id, 0)
        self.assertEqual(
            self.manager.get_all_watchlists(),
            [{"list_id": list_id, "list_name": "半導體"}],
        )

        inserted = self.manager.add_to_watchlist(
            list_id, "2330", "台積電"
        )
        duplicate = self.manager.add_to_watchlist(
            list_id, "2330", "台積電"
        )
        self.assertTrue(inserted)
        self.assertFalse(duplicate)
        self.assertEqual(
            self.manager.get_watchlist_items(list_id),
            [
                {
                    "list_id": list_id,
                    "stock_id": "2330",
                    "stock_name": "台積電",
                }
            ],
        )

        self.assertTrue(self.manager.remove_from_watchlist(list_id, "2330"))
        self.assertEqual(self.manager.get_watchlist_items(list_id), [])
        self.assertTrue(self.manager.delete_watchlist(list_id))
        self.assertEqual(self.manager.get_all_watchlists(), [])

    def test_delete_watchlist_cascades_to_items(self) -> None:
        list_id = self.manager.create_watchlist("AI")
        self.manager.add_to_watchlist(list_id, "2454", "聯發科")

        self.assertTrue(self.manager.delete_watchlist(list_id))
        self.assertEqual(self.manager.get_watchlist_items(list_id), [])

    def test_duplicate_watchlist_name_raises_value_error(self) -> None:
        self.manager.create_watchlist("核心持股")
        with self.assertRaises(ValueError):
            self.manager.create_watchlist("核心持股")


if __name__ == "__main__":
    unittest.main()

"""自選清單 SQLite CRUD 單元測試。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.data_loader import StockDataManager


class TestTechnicalIndicators(unittest.TestCase):
    def test_chandelier_stop_locks_profit_during_reversal(self) -> None:
        rising = np.linspace(50, 100, 30)
        falling = np.array([96, 90, 82, 74, 66, 58, 50], dtype=float)
        close = np.concatenate([rising, falling])
        frame = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=len(close)),
            "open": close - 0.5,
            "max": close + 1.5,
            "min": close - 1.5,
            "close": close,
            "Trading_Money": 1_000_000,
        })

        result = StockDataManager.calculate_indicators(frame, 5, 2.0)

        self.assertIn("Chandelier_Stop", result.columns)
        self.assertTrue(result["Chandelier_Stop"].iloc[4:].notna().all())
        protected_steps = []
        for index in range(5, len(result)):
            previous_stop = result["Chandelier_Stop"].iat[index - 1]
            if result["close"].iat[index - 1] > previous_stop:
                protected_steps.append(index)
                self.assertGreaterEqual(
                    result["Chandelier_Stop"].iat[index], previous_stop,
                    "多頭條件成立時，吊燈停損不得向下移動",
                )
        self.assertTrue(any(index >= 30 for index in protected_steps))

    def test_atr_and_qqe_mod_columns_are_finite(self) -> None:
        periods = 160
        close = 100 + np.linspace(0, 30, periods) + np.sin(np.arange(periods) / 4) * 3
        frame = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=periods, freq="D"),
            "open": close - 0.5,
            "max": close + 2.0,
            "min": close - 2.0,
            "close": close,
            "Trading_Money": np.linspace(1_000_000, 2_000_000, periods),
        })

        result = StockDataManager.calculate_technical_indicators(frame)

        expected = {
            "ATR", "ATR14", "TR", "QQE_Line", "QQE_Signal",
            "QQE_Upper_Band", "QQE_Lower_Band", "QQE_Histogram",
        }
        self.assertTrue(expected.issubset(result.columns))
        self.assertFalse(result[list(expected)].iloc[40:].isna().any().any())
        self.assertTrue(np.isfinite(result[list(expected)].iloc[40:].to_numpy()).all())
        self.assertTrue((result["ATR14"].iloc[40:] > 0).all())


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

    def test_add_stock_with_id_or_name_only(self) -> None:
        list_id = self.manager.create_watchlist("擇一輸入")
        response = {"data": [
            {"stock_id": "2330", "stock_name": "台積電"},
            {"stock_id": "2454", "stock_name": "聯發科"},
        ]}
        with patch.object(self.manager, "_request_json", return_value=response):
            self.assertTrue(self.manager.add_to_watchlist(list_id, stock_id="2330"))
            self.assertTrue(self.manager.add_to_watchlist(list_id, stock_name="聯發科"))
        self.assertEqual(
            [(item["stock_id"], item["stock_name"])
             for item in self.manager.get_watchlist_items(list_id)],
            [("2330", "台積電"), ("2454", "聯發科")],
        )

    def test_add_stock_requires_one_valid_identifier(self) -> None:
        list_id = self.manager.create_watchlist("驗證")
        with self.assertRaisesRegex(ValueError, "股票代碼或公司名稱"):
            self.manager.add_to_watchlist(list_id)
        with patch.object(self.manager, "_request_json", return_value={"data": []}):
            with self.assertRaisesRegex(ValueError, "查無此股票"):
                self.manager.add_to_watchlist(list_id, stock_name="不存在公司")


if __name__ == "__main__":
    unittest.main()

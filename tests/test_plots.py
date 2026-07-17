"""技術圖表與樂活五線譜測試。"""
import unittest
import pandas as pd
from src.plots import calculate_lohas_five_lines, create_advanced_chart


class TestLohasFiveLines(unittest.TestCase):
    def test_straight_prices_produce_equal_trend_lines(self) -> None:
        frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=4),
                              "close": [10, 12, 14, 16]})
        result = calculate_lohas_five_lines(frame)
        for column in ["lohas_upper_2", "lohas_upper_1", "lohas_middle",
                       "lohas_lower_1", "lohas_lower_2"]:
            self.assertEqual(result[column].round(8).tolist(), [10, 12, 14, 16])

    def test_chart_supports_each_secondary_indicator(self) -> None:
        frame = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=3),
            "open": [10, 11, 12], "max": [12, 13, 14], "min": [9, 10, 11],
            "close": [11, 12, 13], "MA20": [None] * 3,
            "Chandelier_Stop": [9.0, 9.5, 10.0],
            "Trading_Money": [100, 200, 300], "MACD": [0.1, 0.2, 0.3],
            "Signal": [0.05, 0.1, 0.2], "DIF": [0.1, 0.2, 0.3],
            "DEA": [0.05, 0.1, 0.2], "Histogram": [0.05, 0.1, 0.1],
            "ATR14": [1.0, 1.1, 1.2], "QQE_Line": [1.0, 2.0, 1.0],
            "QQE_Signal": [0.5, 1.0, 1.5], "QQE_Hist": [0.5, 1.0, -0.5],
        })
        expected = {
            "MACD": {"K 線", "MA20", "吊燈多頭停損", "成交值", "MACD 柱", "DIF", "DEA"},
            "ATR": {"K 線", "MA20", "吊燈多頭停損", "成交值", "ATR (14)"},
            "QQE_MOD": {
                "K 線", "MA20", "吊燈多頭停損", "成交值",
                "QQE 動能", "QQE Line", "QQE Signal",
            },
        }
        for indicator, trace_names in expected.items():
            with self.subTest(indicator=indicator):
                figure = create_advanced_chart(frame, indicator)
                self.assertEqual({trace.name for trace in figure.data}, trace_names)
                self.assertEqual(figure.layout.xaxis.matches, "x2")


if __name__ == "__main__":
    unittest.main()

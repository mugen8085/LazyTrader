"""台股資料、SQLite 快取、自選清單與金融演算法（不依賴 Streamlit）。"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv


class StockDataManager:
    API_URL = "https://api.finmindtrade.com/api/v4/data"
    BROKER_URL = (
        "https://api.finmindtrade.com/api/v4/"
        "taiwan_stock_trading_daily_report_secid_agg"
    )
    DAILY_COLUMNS = [
        "date", "stock_id", "stock_name", "open", "max", "min", "close",
        "Trading_Volume", "Trading_Money", "spread", "Trading_turnover",
    ]
    BROKER_COLUMNS = [
        "date", "stock_id", "broker_id", "broker_name", "buy_volume",
        "sell_volume", "buy_price", "sell_price",
    ]

    def __init__(
        self,
        db_path: str | Path = "stock_system.db",
        token: str | None = None,
        timeout: float = 30.0,
        live_cache_minutes: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        load_dotenv()
        if live_cache_minutes < 0:
            raise ValueError("live_cache_minutes 不可小於 0。")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.token = token or os.getenv("FINMIND_TOKEN")
        self.timeout = timeout
        self.live_cache_duration = timedelta(minutes=live_cache_minutes)
        self.session = session or requests.Session()
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(
            self.db_path, check_same_thread=False, timeout=30
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self._create_tables()

    def _create_tables(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS taiwan_stock_daily (
                date TEXT NOT NULL, stock_id TEXT NOT NULL,
                stock_name TEXT NOT NULL DEFAULT '', open REAL, max REAL,
                min REAL, close REAL, Trading_Volume REAL,
                Trading_Money REAL, spread REAL, Trading_turnover REAL,
                PRIMARY KEY (date, stock_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS taiwan_stock_broker (
                date TEXT NOT NULL, stock_id TEXT NOT NULL,
                broker_id TEXT NOT NULL, broker_name TEXT NOT NULL DEFAULT '',
                buy_volume REAL NOT NULL DEFAULT 0,
                sell_volume REAL NOT NULL DEFAULT 0,
                buy_price REAL, sell_price REAL,
                PRIMARY KEY (date, stock_id, broker_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS watchlists (
                list_id INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name TEXT NOT NULL UNIQUE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS watchlist_items (
                list_id INTEGER NOT NULL, stock_id TEXT NOT NULL,
                stock_name TEXT NOT NULL,
                PRIMARY KEY (list_id, stock_id),
                FOREIGN KEY (list_id) REFERENCES watchlists(list_id)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cache_ranges (
                dataset TEXT NOT NULL, stock_id TEXT NOT NULL,
                start_date TEXT NOT NULL, end_date TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (dataset, stock_id, start_date, end_date)
            )
            """,
            """CREATE INDEX IF NOT EXISTS idx_daily_stock_date
               ON taiwan_stock_daily(stock_id, date)""",
            """CREATE INDEX IF NOT EXISTS idx_broker_stock_date
               ON taiwan_stock_broker(stock_id, date)""",
        ]
        with self._lock, self.connection:
            for statement in statements:
                self.connection.execute(statement)

    def close(self) -> None:
        with self._lock:
            self.session.close()
            self.connection.close()

    def __enter__(self) -> StockDataManager:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _clean_text(value: Any, field_name: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field_name} 不可為空。")
        return text

    @staticmethod
    def _date(value: str | date | datetime) -> date:
        try:
            parsed = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"無效日期：{value}") from exc
        if pd.isna(parsed):
            raise ValueError(f"無效日期：{value}")
        return parsed.date()

    # ---------- Watchlist CRUD ----------
    def create_watchlist(self, name: str) -> int:
        name = self._clean_text(name, "清單名稱")
        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "INSERT INTO watchlists(list_name) VALUES (?)", (name,)
                )
                return int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"自選清單「{name}」已存在。") from exc
        except sqlite3.Error as exc:
            raise RuntimeError(f"建立自選清單失敗：{exc}") from exc

    def get_all_watchlists(self) -> list[dict[str, Any]]:
        try:
            with self._lock:
                rows = self.connection.execute(
                    "SELECT list_id, list_name FROM watchlists ORDER BY list_name"
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise RuntimeError(f"讀取自選清單失敗：{exc}") from exc

    def delete_watchlist(self, list_id: int) -> bool:
        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "DELETE FROM watchlists WHERE list_id = ?", (int(list_id),)
                )
            return cursor.rowcount > 0
        except (TypeError, ValueError) as exc:
            raise ValueError("list_id 必須是整數。") from exc
        except sqlite3.Error as exc:
            raise RuntimeError(f"刪除自選清單失敗：{exc}") from exc

    def add_to_watchlist(
        self, list_id: int, stock_id: str, stock_name: str
    ) -> bool:
        stock_id = self._clean_text(stock_id, "股票代碼")
        stock_name = self._clean_text(stock_name, "公司名稱")
        try:
            with self._lock, self.connection:
                exists = self.connection.execute(
                    "SELECT 1 FROM watchlists WHERE list_id = ?", (int(list_id),)
                ).fetchone()
                if exists is None:
                    raise ValueError("指定的自選清單不存在。")
                cursor = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO watchlist_items
                    (list_id, stock_id, stock_name) VALUES (?, ?, ?)
                    """,
                    (int(list_id), stock_id, stock_name),
                )
            return cursor.rowcount > 0
        except ValueError:
            raise
        except sqlite3.Error as exc:
            raise RuntimeError(f"加入自選股失敗：{exc}") from exc

    def remove_from_watchlist(self, list_id: int, stock_id: str) -> bool:
        stock_id = self._clean_text(stock_id, "股票代碼")
        try:
            with self._lock, self.connection:
                cursor = self.connection.execute(
                    "DELETE FROM watchlist_items WHERE list_id = ? AND stock_id = ?",
                    (int(list_id), stock_id),
                )
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            raise RuntimeError(f"移除自選股失敗：{exc}") from exc

    def get_watchlist_items(self, list_id: int) -> list[dict[str, Any]]:
        try:
            with self._lock:
                rows = self.connection.execute(
                    """
                    SELECT list_id, stock_id, stock_name FROM watchlist_items
                    WHERE list_id = ? ORDER BY stock_id
                    """,
                    (int(list_id),),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise RuntimeError(f"讀取自選股失敗：{exc}") from exc

    # ---------- FinMind and range cache ----------
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.session.get(
                url, params=params, headers=self._headers(), timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            raise RuntimeError("FinMind API 連線逾時。") from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"FinMind API 連線失敗：{exc}") from exc
        except ValueError as exc:
            raise RuntimeError("FinMind API 未回傳有效 JSON。") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("FinMind API 回傳格式不正確。")
        status = payload.get("status")
        if status not in (None, 200):
            message = payload.get("msg") or payload.get("message") or "未知錯誤"
            raise RuntimeError(f"FinMind API 錯誤（{status}）：{message}")
        return payload

    def _request_dataset(
        self, dataset: str, stock_id: str, start: date, end: date
    ) -> pd.DataFrame:
        payload = self._request_json(
            self.API_URL,
            {
                "dataset": dataset,
                "data_id": stock_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        records = payload.get("data")
        if not isinstance(records, list):
            raise RuntimeError("FinMind API 回傳缺少 data 清單。")
        return pd.DataFrame(records)

    def _covered_ranges(self, dataset: str, stock_id: str) -> list[tuple[date, date]]:
        with self._lock:
            rows = self.connection.execute(
                """
                SELECT start_date, end_date, fetched_at FROM cache_ranges
                WHERE dataset = ? AND stock_id = ? ORDER BY start_date
                """,
                (dataset, stock_id),
            ).fetchall()
        now, today = datetime.now(), date.today()
        result = []
        for row in rows:
            start, end = date.fromisoformat(row[0]), date.fromisoformat(row[1])
            fetched_at = datetime.fromisoformat(row[2])
            if end >= today and now - fetched_at >= self.live_cache_duration:
                end = min(end, today - timedelta(days=1))
            if start <= end:
                result.append((start, end))
        return result

    def _missing_ranges(
        self, dataset: str, stock_id: str, start: date, end: date
    ) -> list[tuple[date, date]]:
        merged: list[tuple[date, date]] = []
        for left, right in self._covered_ranges(dataset, stock_id):
            left, right = max(left, start), min(right, end)
            if left > right:
                continue
            if not merged or left > merged[-1][1] + timedelta(days=1):
                merged.append((left, right))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        missing, cursor = [], start
        for left, right in merged:
            if cursor < left:
                missing.append((cursor, left - timedelta(days=1)))
            cursor = max(cursor, right + timedelta(days=1))
        if cursor <= end:
            missing.append((cursor, end))
        return missing

    def _record_range(
        self, dataset: str, stock_id: str, start: date, end: date
    ) -> None:
        self.connection.execute(
            """
            INSERT OR REPLACE INTO cache_ranges
            (dataset, stock_id, start_date, end_date, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                dataset, stock_id, start.isoformat(), end.isoformat(),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def _resolve_stock_name(self, stock_id: str) -> str:
        with self._lock:
            row = self.connection.execute(
                """SELECT stock_name FROM taiwan_stock_daily
                   WHERE stock_id = ? AND stock_name <> '' LIMIT 1""",
                (stock_id,),
            ).fetchone()
        if row:
            return str(row[0])
        try:
            info = self._request_dataset(
                "TaiwanStockInfo", stock_id, date.today(), date.today()
            )
            if not info.empty:
                candidates = info[info.get("stock_id", "").astype(str) == stock_id]
                source = candidates.iloc[0] if not candidates.empty else info.iloc[0]
                return str(source.get("stock_name", source.get("name", stock_id)))
        except (RuntimeError, KeyError, AttributeError):
            pass
        return stock_id

    @staticmethod
    def _number(frame: pd.DataFrame, source: str, default: float = 0) -> pd.Series:
        if source not in frame.columns:
            return pd.Series(default, index=frame.index, dtype="float64")
        return pd.to_numeric(frame[source], errors="coerce").fillna(default)

    def _prepare_daily(self, frame: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=self.DAILY_COLUMNS)
        required = {"date", "open", "max", "min", "close", "Trading_Volume"}
        missing = required.difference(frame.columns)
        if missing:
            raise RuntimeError("股價資料缺少欄位：" + ", ".join(sorted(missing)))
        result = pd.DataFrame(index=frame.index)
        result["date"] = pd.to_datetime(frame["date"], errors="coerce")
        result["stock_id"] = stock_id
        result["stock_name"] = self._resolve_stock_name(stock_id)
        for column in ["open", "max", "min", "close", "Trading_Volume"]:
            result[column] = self._number(frame, column)
        money_source = "Trading_Money" if "Trading_Money" in frame else "Trading_money"
        result["Trading_Money"] = self._number(frame, money_source)
        result["spread"] = self._number(frame, "spread")
        result["Trading_turnover"] = self._number(frame, "Trading_turnover")
        result = result.dropna(subset=["date"])
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
        return result[self.DAILY_COLUMNS].drop_duplicates(["date", "stock_id"])

    def _prepare_broker(self, frame: pd.DataFrame, stock_id: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=self.BROKER_COLUMNS)
        aliases = {
            "broker_id": ["broker_id", "securities_trader_id"],
            "broker_name": ["broker_name", "securities_trader"],
        }
        broker_id = next((x for x in aliases["broker_id"] if x in frame), None)
        broker_name = next((x for x in aliases["broker_name"] if x in frame), None)
        if "date" not in frame or broker_id is None:
            raise RuntimeError("分點資料缺少 date 或券商代碼欄位。")
        result = pd.DataFrame(index=frame.index)
        result["date"] = pd.to_datetime(frame["date"], errors="coerce")
        result["stock_id"] = stock_id
        result["broker_id"] = frame[broker_id].astype(str)
        result["broker_name"] = (
            frame[broker_name].fillna("").astype(str) if broker_name else result["broker_id"]
        )
        for column in ["buy_volume", "sell_volume", "buy_price", "sell_price"]:
            result[column] = self._number(frame, column)
        result = result.dropna(subset=["date"])
        result["date"] = result["date"].dt.strftime("%Y-%m-%d")
        return result[self.BROKER_COLUMNS].drop_duplicates(
            ["date", "stock_id", "broker_id"]
        )

    def _insert_ignore(self, table: str, columns: list[str], frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        values = [
            tuple(None if pd.isna(value) else value for value in row)
            for row in frame[columns].itertuples(index=False, name=None)
        ]
        self.connection.executemany(
            f"INSERT OR IGNORE INTO {table} ({column_sql}) VALUES ({placeholders})",
            values,
        )

    def get_clean_daily_data(
        self, stock_id: str, start_date: str | date, end_date: str | date
    ) -> pd.DataFrame:
        stock_id = self._clean_text(stock_id, "股票代碼")
        start, end = self._date(start_date), self._date(end_date)
        if start > end:
            raise ValueError("起始日期不可晚於結束日期。")
        for left, right in self._missing_ranges("daily", stock_id, start, end):
            raw = self._request_dataset("TaiwanStockPrice", stock_id, left, right)
            prepared = self._prepare_daily(raw, stock_id)
            try:
                with self._lock, self.connection:
                    self._insert_ignore(
                        "taiwan_stock_daily", self.DAILY_COLUMNS, prepared
                    )
                    self._record_range("daily", stock_id, left, right)
            except sqlite3.Error as exc:
                raise RuntimeError(f"寫入股價快取失敗：{exc}") from exc
        with self._lock:
            result = pd.read_sql_query(
                """SELECT * FROM taiwan_stock_daily
                   WHERE stock_id = ? AND date BETWEEN ? AND ? ORDER BY date""",
                self.connection,
                params=(stock_id, start.isoformat(), end.isoformat()),
            )
        return self.calculate_technical_indicators(result)

    def _request_broker_data(
        self, stock_id: str, start: date, end: date
    ) -> pd.DataFrame:
        payload = self._request_json(
            self.BROKER_URL,
            {
                "stock_id": stock_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        records = payload.get("data")
        if not isinstance(records, list):
            raise RuntimeError("分點 API 回傳缺少 data 清單。")
        return pd.DataFrame(records)

    def get_broker_data(
        self, stock_id: str, start_date: str | date, end_date: str | date
    ) -> pd.DataFrame:
        stock_id = self._clean_text(stock_id, "股票代碼")
        start, end = self._date(start_date), self._date(end_date)
        if start > end:
            raise ValueError("起始日期不可晚於結束日期。")
        for left, right in self._missing_ranges("broker", stock_id, start, end):
            raw = self._request_broker_data(stock_id, left, right)
            prepared = self._prepare_broker(raw, stock_id)
            try:
                with self._lock, self.connection:
                    self._insert_ignore(
                        "taiwan_stock_broker", self.BROKER_COLUMNS, prepared
                    )
                    self._record_range("broker", stock_id, left, right)
            except sqlite3.Error as exc:
                raise RuntimeError(f"寫入分點快取失敗：{exc}") from exc
        with self._lock:
            result = pd.read_sql_query(
                """SELECT * FROM taiwan_stock_broker
                   WHERE stock_id = ? AND date BETWEEN ? AND ?
                   ORDER BY date, broker_id""",
                self.connection,
                params=(stock_id, start.isoformat(), end.isoformat()),
            )
        if not result.empty:
            result["date"] = pd.to_datetime(result["date"], errors="coerce")
        return result

    @staticmethod
    def calculate_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        if result.empty:
            for column in ["MA20", "EMA12", "EMA26", "MACD", "Signal", "Histogram"]:
                result[column] = pd.Series(dtype="float64")
            return result
        required = {"date", "close"}
        if missing := required.difference(result.columns):
            raise ValueError("技術指標缺少欄位：" + ", ".join(sorted(missing)))
        result["date"] = pd.to_datetime(result["date"], errors="coerce")
        result["close"] = pd.to_numeric(result["close"], errors="coerce")
        result = result.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
        result["MA20"] = result["close"].rolling(20, min_periods=20).mean()
        result["EMA12"] = result["close"].ewm(span=12, adjust=False).mean()
        result["EMA26"] = result["close"].ewm(span=26, adjust=False).mean()
        result["MACD"] = result["EMA12"] - result["EMA26"]
        result["Signal"] = result["MACD"].ewm(span=9, adjust=False).mean()
        result["Histogram"] = result["MACD"] - result["Signal"]
        return result

    @staticmethod
    def calculate_kpi_metrics(df: pd.DataFrame) -> dict[str, float]:
        if df.empty:
            raise ValueError("無法從空資料計算 KPI。")
        required = {"date", "close", "Trading_Money"}
        if missing := required.difference(df.columns):
            raise ValueError("KPI 缺少欄位：" + ", ".join(sorted(missing)))
        ordered = df.sort_values("date").reset_index(drop=True)
        latest_close = float(ordered.iloc[-1]["close"])
        previous = float(ordered.iloc[-2]["close"]) if len(ordered) > 1 else float("nan")
        change = latest_close - previous if pd.notna(previous) else float("nan")
        percent = change / previous * 100 if pd.notna(previous) and previous else float("nan")
        return {
            "latest_close": latest_close,
            "price_change": change,
            "change_percent": percent,
            "trading_money": float(ordered.iloc[-1]["Trading_Money"]),
        }

    @staticmethod
    def calculate_broker_summary(
        df_broker: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        columns = ["broker_id", "broker_name", "buy_volume", "sell_volume", "net_buy"]
        if df_broker.empty:
            empty = pd.DataFrame(columns=columns)
            return empty.copy(), empty.copy()
        required = {"broker_id", "broker_name", "buy_volume", "sell_volume"}
        if missing := required.difference(df_broker.columns):
            raise ValueError("分點彙總缺少欄位：" + ", ".join(sorted(missing)))
        summary = (
            df_broker.groupby(["broker_id", "broker_name"], as_index=False)[
                ["buy_volume", "sell_volume"]
            ].sum()
        )
        summary["net_buy"] = summary["buy_volume"] - summary["sell_volume"]
        top_buy = summary.nlargest(5, "net_buy").reset_index(drop=True)
        top_sell = summary.nsmallest(5, "net_buy").reset_index(drop=True)
        return top_buy[columns], top_sell[columns]

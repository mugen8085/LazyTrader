"""台股全功能金融數據儀表板。"""

from __future__ import annotations

import importlib
import inspect
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src import data_loader as data_loader_module
from src import plots as plots_module


# Streamlit 會在同一個 Python 行程重跑 app.py，而一般 from ... import ...
# 可能繼續指向 sys.modules 中的舊函式物件。明確 reload 可確保 plots.py 修改後
# 立即套用，特別是 create_advanced_chart 新增參數時。
plots_module = importlib.reload(plots_module)
data_loader_module = importlib.reload(data_loader_module)
StockDataManager = data_loader_module.StockDataManager


def _validate_plot_api() -> None:
    parameters = inspect.signature(plots_module.create_advanced_chart).parameters
    if "indicator_type" not in parameters:
        raise RuntimeError(
            "載入到舊版 src.plots：create_advanced_chart 缺少 indicator_type 參數。"
            "請確認執行目錄為專案根目錄後重新啟動 Streamlit。"
        )


_validate_plot_api()


st.set_page_config(
    page_title="台股全功能金融數據儀表板", page_icon="📈", layout="wide"
)


@st.cache_resource
def get_manager(cache_version: str = "chandelier-v1") -> StockDataManager:
    """建立資料管理器；cache_version 用來淘汰舊類別建立的快取實例。"""
    return StockDataManager(db_path="stock_system.db")


def initialize_state() -> None:
    defaults = {"stock_id": "2330", "stock_name": "台積電"}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("flash", None)
    if item:
        kind, message = item
        getattr(st, kind, st.info)(message)


def sidebar_watchlists(manager: StockDataManager) -> int | None:
    st.sidebar.header("自選清單管理")
    with st.sidebar.form("create_watchlist", clear_on_submit=True):
        name = st.text_input("新增清單名稱")
        if st.form_submit_button("建立清單", use_container_width=True):
            try:
                manager.create_watchlist(name)
                flash("success", f"已建立自選清單：{name.strip()}")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))

    watchlists = manager.get_all_watchlists()
    if not watchlists:
        st.sidebar.info("尚無自選清單，請先建立一個清單。")
        return None

    labels = {row["list_id"]: row["list_name"] for row in watchlists}
    selected_id = st.sidebar.selectbox(
        "自選股清單切換",
        options=list(labels),
        format_func=lambda value: labels[value],
        key="selected_watchlist_id",
    )
    with st.sidebar.form("rename_watchlist", clear_on_submit=True):
        new_name = st.text_input("清單新名稱")
        if st.form_submit_button("重新命名", use_container_width=True):
            try:
                manager.rename_watchlist(selected_id, new_name)
                flash("success", "自選清單已重新命名。")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))
    if st.sidebar.button("刪除此清單", type="secondary", use_container_width=True):
        try:
            manager.delete_watchlist(selected_id)
            st.session_state.pop("selected_watchlist_id", None)
            flash("success", "自選清單已刪除。")
            st.rerun()
        except RuntimeError as exc:
            st.sidebar.error(str(exc))

    st.sidebar.subheader("清單內股票")
    items = manager.get_watchlist_items(selected_id)
    if not items:
        st.sidebar.caption("此清單尚無股票。")
    for item in items:
        left, right = st.sidebar.columns([5, 1])
        if left.button(
            f"{item['stock_id']}　{item['stock_name']}",
            key=f"pick_{selected_id}_{item['stock_id']}",
            use_container_width=True,
        ):
            st.session_state.stock_id = item["stock_id"]
            st.session_state.stock_name = item["stock_name"]
            st.rerun()
        if right.button(
            "✕", key=f"remove_{selected_id}_{item['stock_id']}", help="移除"
        ):
            manager.remove_from_watchlist(selected_id, item["stock_id"])
            st.rerun()

    return selected_id


def query_controls() -> tuple[date, date, int, float]:
    st.sidebar.divider()
    st.sidebar.header("吊燈停損參數")
    period = st.sidebar.slider("回看天數（Period）", 5, 60, 22, 1)
    multiplier = st.sidebar.slider("ATR 乘數（Multiplier）", 1.0, 6.0, 3.0, 0.1)
    st.sidebar.header("時間範圍")
    today = date.today()
    start = st.sidebar.date_input("起始日期", today - timedelta(days=365))
    end = st.sidebar.date_input("結束日期", today, max_value=today)
    return start, end, period, multiplier


def metric_delta(metrics: dict[str, float]) -> str | None:
    if pd.isna(metrics["price_change"]) or pd.isna(metrics["change_percent"]):
        return None
    return f"{metrics['price_change']:+.2f}（{metrics['change_percent']:+.2f}%）"


def main() -> None:
    initialize_state()
    manager = get_manager("chandelier-v1")
    st.title("台股全功能金融數據儀表板")
    st.caption("FinMind × SQLite × Plotly")
    show_flash()

    try:
        selected_list_id = sidebar_watchlists(manager)
        start, end, chandelier_period, chandelier_mult = query_controls()
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
        return

    input_id, input_name, add_column = st.columns([2, 3, 2])
    stock_id = input_id.text_input("股票代碼", key="stock_id").strip()
    stock_name = input_name.text_input("公司名稱", key="stock_name").strip()
    add_column.write("")
    add_column.write("")
    if add_column.button(
        "加入當前選取清單", type="primary", use_container_width=True,
        disabled=selected_list_id is None,
    ):
        try:
            inserted = manager.add_to_watchlist(
                int(selected_list_id), stock_id, stock_name
            )
            flash(
                "success" if inserted else "info",
                "股票已加入自選清單。" if inserted else "股票已在此清單中。",
            )
            st.rerun()
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))

    if not stock_id:
        st.info("請輸入股票代碼。")
        return
    if start > end:
        st.error("起始日期不可晚於結束日期。")
        return

    try:
        with st.spinner("載入股價與技術指標……"):
            daily = manager.get_clean_daily_data(
                stock_id, start, end, chandelier_period, chandelier_mult
            )
    except (ValueError, RuntimeError) as exc:
        st.error(f"股價資料載入失敗：{exc}")
        return
    if daily.empty:
        st.warning("查無股價資料，請確認代碼與日期區間。")
        return

    resolved_name = stock_name or str(daily.iloc[-1].get("stock_name", stock_id))
    st.subheader(f"{stock_id}　{resolved_name}")
    metrics = manager.calculate_kpi_metrics(daily)
    col1, col2, col3, col4 = st.columns(4)
    stop = metrics["chandelier_stop"]
    holding = pd.notna(stop) and metrics["latest_close"] > stop
    col1.metric("最新收盤價", f"NT$ {metrics['latest_close']:,.2f}",
                delta=metric_delta(metrics))
    col2.metric("今日成交值", f"{metrics['trading_money'] / 100_000_000:,.2f} 億")
    col3.metric("當前吊燈停損價", f"NT$ {stop:,.2f}" if pd.notna(stop) else "暖機中")
    col4.metric("趨勢風向控管", "🍏 持股續抱" if holding else "🚨 跌破退場")

    indicator_labels = {
        "MACD 動能": "MACD",
        "ATR 波動度": "ATR",
        "QQE_MOD 趨勢": "QQE_MOD",
    }
    selected_label = st.radio(
        "副圖技術指標",
        options=list(indicator_labels),
        horizontal=True,
        key="selected_indicator",
        help="切換下方副圖；K 線、MA20 與成交值會保持不變。",
    )
    selected_type = indicator_labels[selected_label]
    try:
        chart = plots_module.create_advanced_chart(
            daily, indicator_type=selected_type
        )
        st.plotly_chart(chart, use_container_width=True, config={"displaylogo": False})
    except ValueError as exc:
        st.error(f"圖表建立失敗：{exc}")

    broker_tab, history_tab = st.tabs(["主力分點分析", "歷史明細"])
    with broker_tab:
        try:
            with st.spinner("載入券商分點資料……"):
                broker = manager.get_broker_data(stock_id, start, end)
            buy, sell = manager.calculate_broker_summary(broker)
            if broker.empty:
                st.info("此區間查無券商分點資料。")
            else:
                left, right = st.columns(2)
                left.markdown("#### 買超前五大")
                left.dataframe(buy, use_container_width=True, hide_index=True)
                right.markdown("#### 賣超前五大")
                right.dataframe(sell, use_container_width=True, hide_index=True)
                buy_chart = px.bar(
                    buy.sort_values("net_buy"), x="net_buy", y="broker_name",
                    orientation="h", title="買超前五大", color_discrete_sequence=["#ef5350"],
                )
                sell_chart = px.bar(
                    sell.sort_values("net_buy", ascending=False),
                    x="net_buy", y="broker_name", orientation="h",
                    title="賣超前五大", color_discrete_sequence=["#26a69a"],
                )
                buy_chart.update_layout(template="plotly_dark", margin=dict(l=10, r=10, t=45, b=10))
                sell_chart.update_layout(template="plotly_dark", margin=dict(l=10, r=10, t=45, b=10))
                chart_left, chart_right = st.columns(2)
                chart_left.plotly_chart(buy_chart, use_container_width=True)
                chart_right.plotly_chart(sell_chart, use_container_width=True)
        except (ValueError, RuntimeError) as exc:
            st.warning(
                "券商分點資料載入失敗。此資料集可能需要 FinMind 贊助會員權限。"
            )
            st.code(str(exc))
    with history_tab:
        st.dataframe(
            daily.sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )


if __name__ == "__main__":
    main()

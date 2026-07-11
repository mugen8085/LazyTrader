"""台股全功能金融數據儀表板。"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src.data_loader import StockDataManager
from src.plots import create_advanced_chart, create_broker_bar_chart


st.set_page_config(
    page_title="台股全功能金融數據儀表板", page_icon="📈", layout="wide"
)


@st.cache_resource
def get_manager() -> StockDataManager:
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


def sidebar_watchlists(manager: StockDataManager) -> None:
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
        return

    labels = {row["list_id"]: row["list_name"] for row in watchlists}
    selected_id = st.sidebar.selectbox(
        "自選股清單切換",
        options=list(labels),
        format_func=lambda value: labels[value],
        key="selected_watchlist_id",
    )
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

    st.sidebar.subheader("加股票到自選")
    with st.sidebar.form("add_stock", clear_on_submit=False):
        add_id = st.text_input("股票代碼", key="watch_add_stock_id")
        add_name = st.text_input("公司名稱", key="watch_add_stock_name")
        target = st.selectbox(
            "加入清單", options=list(labels), format_func=lambda value: labels[value]
        )
        if st.form_submit_button("加入自選", use_container_width=True):
            try:
                inserted = manager.add_to_watchlist(target, add_id, add_name)
                if inserted:
                    flash("success", "股票已加入自選清單。")
                else:
                    flash("info", "此股票已存在於該清單。")
                st.rerun()
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))


def query_controls() -> tuple[str, str, date, date, bool]:
    st.sidebar.divider()
    st.sidebar.header("資料查詢")
    stock_id = st.sidebar.text_input("查詢股票代碼", key="stock_id").strip()
    stock_name = st.sidebar.text_input("公司名稱", key="stock_name").strip()
    today = date.today()
    start = st.sidebar.date_input("起始日期", today - timedelta(days=365))
    end = st.sidebar.date_input("結束日期", today, max_value=today)
    submitted = st.sidebar.button("載入資料", type="primary", use_container_width=True)
    return stock_id, stock_name, start, end, submitted


def metric_delta(metrics: dict[str, float]) -> str | None:
    if pd.isna(metrics["price_change"]) or pd.isna(metrics["change_percent"]):
        return None
    return f"{metrics['price_change']:+.2f}（{metrics['change_percent']:+.2f}%）"


def main() -> None:
    initialize_state()
    manager = get_manager()
    st.title("台股全功能金融數據儀表板")
    st.caption("FinMind × SQLite × Plotly")
    show_flash()

    try:
        sidebar_watchlists(manager)
        stock_id, stock_name, start, end, _ = query_controls()
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
        return

    if not stock_id:
        st.info("請輸入股票代碼。")
        return
    if start > end:
        st.error("起始日期不可晚於結束日期。")
        return

    try:
        with st.spinner("載入股價與技術指標……"):
            daily = manager.get_clean_daily_data(stock_id, start, end)
    except (ValueError, RuntimeError) as exc:
        st.error(f"股價資料載入失敗：{exc}")
        return
    if daily.empty:
        st.warning("查無股價資料，請確認代碼與日期區間。")
        return

    resolved_name = stock_name or str(daily.iloc[-1].get("stock_name", stock_id))
    st.subheader(f"{stock_id}　{resolved_name}")
    metrics = manager.calculate_kpi_metrics(daily)
    col1, col2, col3 = st.columns(3)
    col1.metric(
        "最新收盤價", f"NT$ {metrics['latest_close']:,.2f}",
        delta=metric_delta(metrics),
    )
    col2.metric("漲跌幅", f"{metrics['change_percent']:+.2f}%" if pd.notna(metrics["change_percent"]) else "—")
    col3.metric("今日成交值", f"NT$ {metrics['trading_money']:,.0f}")
    st.plotly_chart(create_advanced_chart(daily), use_container_width=True)

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
                st.plotly_chart(
                    create_broker_bar_chart(buy, sell), use_container_width=True
                )
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

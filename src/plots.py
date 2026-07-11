"""台股專業互動圖表（不依賴 Streamlit）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def create_advanced_chart(df: pd.DataFrame) -> go.Figure:
    required = {
        "date", "open", "max", "min", "close", "MA20",
        "Trading_Money", "MACD", "Signal", "Histogram",
    }
    if missing := required.difference(df.columns):
        raise ValueError("繪圖資料缺少欄位：" + ", ".join(sorted(missing)))

    rising = pd.to_numeric(df["close"], errors="coerce") >= pd.to_numeric(
        df["open"], errors="coerce"
    )
    price_colors = ["#ef5350" if value else "#26a69a" for value in rising]
    macd_colors = [
        "#ef5350" if value >= 0 else "#26a69a"
        for value in pd.to_numeric(df["Histogram"], errors="coerce").fillna(0)
    ]

    figure = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.035,
        row_heights=[0.6, 0.2, 0.2],
        subplot_titles=("股價與 MA20", "成交值", "MACD"),
    )
    figure.add_trace(
        go.Candlestick(
            x=df["date"], open=df["open"], high=df["max"], low=df["min"],
            close=df["close"], name="K 線",
            increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=df["date"], y=df["MA20"], mode="lines", name="MA20",
            line={"color": "#ffca28", "width": 2},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=df["date"], y=df["Trading_Money"], name="成交值",
            marker_color=price_colors,
            hovertemplate="%{x|%Y-%m-%d}<br>成交值：%{y:,.0f}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=df["date"], y=df["Histogram"], name="Histogram",
            marker_color=macd_colors,
        ),
        row=3,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=df["date"], y=df["MACD"], mode="lines", name="MACD",
            line={"color": "#42a5f5", "width": 1.8},
        ),
        row=3,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=df["date"], y=df["Signal"], mode="lines", name="Signal",
            line={"color": "#ffa726", "width": 1.8},
        ),
        row=3,
        col=1,
    )
    figure.update_layout(
        template="plotly_dark",
        title="台股技術分析：K 線、成交值與 MACD",
        height=900,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        margin={"l": 30, "r": 20, "t": 100, "b": 30},
        bargap=0.1,
    )
    figure.update_yaxes(title_text="股價", row=1, col=1)
    figure.update_yaxes(title_text="成交值", tickformat="~s", row=2, col=1)
    figure.update_yaxes(title_text="MACD", row=3, col=1)
    figure.update_xaxes(title_text="日期", row=3, col=1)
    return figure


def create_broker_bar_chart(
    top_buy: pd.DataFrame, top_sell: pd.DataFrame
) -> go.Figure:
    figure = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("買超前五大", "賣超前五大"),
        horizontal_spacing=0.14,
    )
    if not top_buy.empty:
        buy = top_buy.sort_values("net_buy")
        figure.add_trace(
            go.Bar(
                x=buy["net_buy"], y=buy["broker_name"], orientation="h",
                name="買超", marker_color="#ef5350",
            ),
            row=1,
            col=1,
        )
    if not top_sell.empty:
        sell = top_sell.sort_values("net_buy", ascending=False)
        figure.add_trace(
            go.Bar(
                x=sell["net_buy"], y=sell["broker_name"], orientation="h",
                name="賣超", marker_color="#26a69a",
            ),
            row=1,
            col=2,
        )
    figure.update_layout(
        template="plotly_dark", height=430, showlegend=False,
        margin={"l": 20, "r": 20, "t": 60, "b": 30},
    )
    figure.update_xaxes(title_text="淨買賣股數")
    return figure

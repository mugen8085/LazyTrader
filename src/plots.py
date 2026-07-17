"""台股專業互動圖表（不依賴 Streamlit）。"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def calculate_lohas_five_lines(df: pd.DataFrame) -> pd.DataFrame:
    """依收盤價線性回歸及殘差標準差計算樂活五線譜。"""
    if missing := {"date", "close"}.difference(df.columns):
        raise ValueError("五線譜資料缺少欄位：" + ", ".join(sorted(missing)))
    result = pd.DataFrame({
        "date": pd.to_datetime(df["date"], errors="coerce"),
        "close": pd.to_numeric(df["close"], errors="coerce"),
    }).dropna().sort_values("date")
    if len(result) < 2:
        raise ValueError("樂活五線譜至少需要兩筆有效股價資料。")
    x = pd.Series(range(len(result)), index=result.index, dtype="float64")
    centered = x - x.mean()
    denominator = (centered ** 2).sum()
    slope = (centered * (result["close"] - result["close"].mean())).sum()
    slope = slope / denominator if denominator else 0.0
    middle = result["close"].mean() + slope * centered
    deviation = (result["close"] - middle).std(ddof=0)
    result["lohas_upper_2"] = middle + 2 * deviation
    result["lohas_upper_1"] = middle + deviation
    result["lohas_middle"] = middle
    result["lohas_lower_1"] = middle - deviation
    result["lohas_lower_2"] = middle - 2 * deviation
    return result.drop(columns="close").reset_index(drop=True)


def create_advanced_chart(
    df: pd.DataFrame, indicator_type: str = "MACD"
) -> go.Figure:
    """建立價量合一主圖與一個可切換的技術指標副圖。"""
    indicator = str(indicator_type).strip().upper()
    indicator_columns = {
        "MACD": {"DIF", "DEA", "Histogram"},
        "ATR": {"ATR14"},
        "QQE_MOD": {"QQE_Line", "QQE_Signal", "QQE_Hist"},
    }
    if indicator not in indicator_columns:
        choices = ", ".join(indicator_columns)
        raise ValueError(f"不支援的指標：{indicator_type}；可用值為 {choices}")

    required = {
        "date", "open", "max", "min", "close", "MA20", "Chandelier_Stop",
        "Trading_Money"
    } | indicator_columns[indicator]
    if missing := required.difference(df.columns):
        raise ValueError("繪圖資料缺少欄位：" + ", ".join(sorted(missing)))
    if df.empty:
        raise ValueError("無法使用空的 DataFrame 建立圖表。")

    chart_data = df.copy()
    chart_data["date"] = pd.to_datetime(chart_data["date"], errors="coerce")
    chart_data = chart_data.dropna(subset=["date"]).sort_values("date")
    if chart_data.empty:
        raise ValueError("繪圖資料沒有有效日期。")

    rising = pd.to_numeric(chart_data["close"], errors="coerce") >= pd.to_numeric(
        chart_data["open"], errors="coerce"
    )
    market_colors = ["#ef5350" if value else "#26a69a" for value in rising]

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.045,
        row_heights=[0.72, 0.28],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )
    figure.add_trace(
        go.Candlestick(
            x=chart_data["date"],
            open=chart_data["open"],
            high=chart_data["max"],
            low=chart_data["min"],
            close=chart_data["close"],
            name="K 線",
            increasing_line_color="#ef5350",
            decreasing_line_color="#26a69a",
            hoverlabel={"namelength": -1},
        ),
        row=1, col=1, secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=chart_data["date"], y=chart_data["MA20"],
            mode="lines", name="MA20",
            line={"color": "#ffd54f", "width": 1.8},
            hovertemplate="%{x|%Y-%m-%d}<br>MA20：%{y:,.2f}<extra></extra>",
        ),
        row=1, col=1, secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=chart_data["date"], y=chart_data["Chandelier_Stop"],
            mode="lines", name="吊燈多頭停損",
            line={"color": "#00E5FF", "width": 2, "dash": "dashdot", "shape": "hv"},
            hovertemplate="%{x|%Y-%m-%d}<br>吊燈停損：%{y:,.2f}<extra></extra>",
        ),
        row=1, col=1, secondary_y=False,
    )
    figure.add_trace(
        go.Bar(
            x=chart_data["date"], y=chart_data["Trading_Money"],
            marker_color=market_colors, opacity=0.15,
            name="成交值", showlegend=False,
            hovertemplate="%{x|%Y-%m-%d}<br>成交值：%{y:,.0f}<extra></extra>",
        ),
        row=1, col=1, secondary_y=True,
    )

    if indicator == "MACD":
        histogram = pd.to_numeric(chart_data["Histogram"], errors="coerce").fillna(0)
        colors = ["#ef5350" if value >= 0 else "#26a69a" for value in histogram]
        figure.add_trace(
            go.Bar(x=chart_data["date"], y=histogram, name="MACD 柱",
                   marker_color=colors), row=2, col=1,
        )
        figure.add_trace(
            go.Scatter(x=chart_data["date"], y=chart_data["DIF"], mode="lines",
                       name="DIF", line={"color": "#42a5f5", "width": 1.8}),
            row=2, col=1,
        )
        figure.add_trace(
            go.Scatter(x=chart_data["date"], y=chart_data["DEA"], mode="lines",
                       name="DEA", line={"color": "#ffa726", "width": 1.8}),
            row=2, col=1,
        )
        subtitle, y_title = "MACD 動能", "MACD"
    elif indicator == "ATR":
        figure.add_trace(
            go.Scatter(
                x=chart_data["date"], y=chart_data["ATR14"], mode="lines",
                name="ATR (14)", line={"color": "#ce93d8", "width": 2.2},
                fill="tozeroy", fillcolor="rgba(206,147,216,0.10)",
            ), row=2, col=1,
        )
        subtitle, y_title = "ATR 波動度", "ATR (14)"
    else:
        histogram = pd.to_numeric(
            chart_data["QQE_Hist"], errors="coerce"
        ).fillna(0)
        colors = ["#ef5350" if value >= 0 else "#26a69a" for value in histogram]
        figure.add_trace(
            go.Bar(x=chart_data["date"], y=histogram, name="QQE 動能",
                   marker_color=colors), row=2, col=1,
        )
        figure.add_trace(
            go.Scatter(x=chart_data["date"], y=chart_data["QQE_Line"],
                       mode="lines", name="QQE Line",
                       line={"color": "#ffee58", "width": 1.8}), row=2, col=1,
        )
        figure.add_trace(
            go.Scatter(x=chart_data["date"], y=chart_data["QQE_Signal"],
                       mode="lines", name="QQE Signal",
                       line={"color": "#42a5f5", "width": 1.6}), row=2, col=1,
        )
        subtitle, y_title = "QQE_MOD 趨勢", "QQE"

    figure.update_layout(
        template="plotly_dark",
        title={"text": f"價量走勢｜{subtitle}", "x": 0.01, "xanchor": "left"},
        height=760,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend={
            "orientation": "h", "x": 0, "y": 1.01,
            "xanchor": "left", "yanchor": "bottom",
        },
        margin={"l": 12, "r": 12, "t": 55, "b": 12},
        bargap=0.12,
    )
    figure.update_yaxes(title_text="股價", row=1, col=1, secondary_y=False)
    figure.update_yaxes(
        title_text="", tickformat="~s", showgrid=False, showticklabels=False,
        rangemode="tozero", row=1, col=1, secondary_y=True,
    )
    figure.update_yaxes(title_text=y_title, zeroline=True, row=2, col=1)
    figure.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor")
    figure.update_xaxes(title_text="日期", row=2, col=1)
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

"""
Generates a small candlestick chart image (last N candles) with the
signal candle highlighted, so Jerry can visually confirm which bar
and timeframe triggered the alert.
"""
import mplfinance as mpf
import pandas as pd


def generate_chart(candles, signal_candle_time, title, out_path, lookback=20):
    """
    candles: list of completed candles, oldest -> newest (needs volume too)
    signal_candle_time: the "time" string of the candle that triggered the signal
    title: chart title
    out_path: file path to save PNG to
    """
    window = candles[-lookback:]
    df = pd.DataFrame(window)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    signal_ts = pd.to_datetime(signal_candle_time)
    marker_offset = (df["High"].max() - df["Low"].min()) * 0.03
    markers = [
        (df.loc[idx, "High"] + marker_offset) if idx == signal_ts else float("nan")
        for idx in df.index
    ]

    add_plots = [
        mpf.make_addplot(
            markers, type="scatter", markersize=120, marker="v", color="red"
        )
    ]

    mpf.plot(
        df,
        type="candle",
        style="charles",
        addplot=add_plots,
        volume=True,
        title=title,
        savefig=dict(fname=out_path, dpi=130, bbox_inches="tight"),
    )

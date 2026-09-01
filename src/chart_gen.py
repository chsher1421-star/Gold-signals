"""
Generates a small candlestick chart image (last N candles) with the
signal candle highlighted, so Jerry can visually confirm which bar
and timeframe triggered the alert.

For CAB alerts (show_volume_bands=True), the volume panel is replaced
with the "Relative Volume [ND]" indicator (by Sajid Khan Ghori) that
Jerry uses on TradingView: SMA(volume, 14) baseline with bands at
0.5x / 1.9x / 2.2x / 3.5x, plus the same per-bar coloring logic. This
lets the alert chart visually confirm the same "very high" / "ultra
high" tier that vsa_signals.check_cab() used to decide the signal -
the underlying indicator math is untouched, only wired into the chart.
"""
import mplfinance as mpf
import pandas as pd
import matplotlib.pyplot as plt

VOL_SMA_LEN = 14
VOL_BAND_LOW = 0.5
VOL_BAND_MID = 1.9      # "high" - informational band, does not fire a CAB
VOL_BAND_HIGH = 2.2     # "very high" - fires a CAB
VOL_BAND_ULTRA = 3.5    # "ultra high" - fires a CAB


def _volume_bar_colors(volumes, opens, closes):
    """
    Same coloring rule as the Pine Script:
    magenta = volume below both previous 2 bars (No Demand/No Supply zone)
    blue    = volume above either previous bar, bullish candle
    red     = volume above either previous bar, bearish candle
    black   = anything else
    """
    colors = []
    for i in range(len(volumes)):
        v = volumes[i]
        v1 = volumes[i - 1] if i >= 1 else v
        v2 = volumes[i - 2] if i >= 2 else v
        if v < v1 and v < v2:
            colors.append("#f321cb")
        elif (v > v1 or v > v2) and closes[i] > opens[i]:
            colors.append("#2962ff")
        elif (v > v1 or v > v2) and closes[i] < opens[i]:
            colors.append("#ff1744")
        else:
            colors.append("#000000")
    return colors


def generate_chart(candles, signal_candle_time, title, out_path, lookback=20,
                    show_volume_bands=False):
    """
    candles: list of completed candles, oldest -> newest (needs volume too)
    signal_candle_time: the "time" string of the candle that triggered the signal
    title: chart title
    out_path: file path to save PNG to
    show_volume_bands: pass True for CAB alerts to draw the SMA(14)
        volume-band indicator instead of plain volume bars.
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

    if not show_volume_bands:
        mpf.plot(
            df,
            type="candle",
            style="charles",
            addplot=add_plots,
            volume=True,
            title=title,
            savefig=dict(fname=out_path, dpi=130, bbox_inches="tight"),
        )
        return

    # --- CAB alert: candlestick panel + SMA(14) volume-band indicator panel ---
    fig, axes = mpf.plot(
        df,
        type="candle",
        style="charles",
        addplot=add_plots,
        volume=False,
        title=title,
        returnfig=True,
        figsize=(9, 7),
    )
    ax_price = axes[0]

    # SMA(14) is computed over the FULL candle history passed in (not just
    # the visible lookback window) so it isn't distorted by only seeing a
    # 20-bar slice - matches how vsa_signals.check_cab() computes it.
    full_df = pd.DataFrame(candles)
    full_df["time"] = pd.to_datetime(full_df["time"])
    full_df = full_df.set_index("time")
    sma14_full = full_df["volume"].rolling(VOL_SMA_LEN).mean()

    vol_window = full_df.loc[df.index[0]: df.index[-1]]
    sma14 = sma14_full.loc[df.index[0]: df.index[-1]]

    volumes = vol_window["volume"].tolist()
    opens = vol_window["open"].tolist()
    closes = vol_window["close"].tolist()
    x = list(range(len(volumes)))

    pos = ax_price.get_position()
    ax_vol = fig.add_axes([pos.x0, 0.06, pos.width, 0.20])

    band_low = sma14 * VOL_BAND_LOW
    band_mid = sma14 * VOL_BAND_MID
    band_high = sma14 * VOL_BAND_HIGH
    band_ultra = sma14 * VOL_BAND_ULTRA

    ax_vol.fill_between(x, band_low, band_mid, color="#0965f5", alpha=0.19)
    ax_vol.fill_between(x, band_mid, band_high, color="#ffcdd2", alpha=0.39)
    ax_vol.fill_between(x, band_high, band_ultra, color="#e57373", alpha=0.61)
    ax_vol.plot(x, sma14, color="black", linewidth=1.3, label="SMA(14)")

    colors = _volume_bar_colors(volumes, opens, closes)
    ax_vol.bar(x, volumes, color=colors, width=0.7)

    ax_vol.set_xlim(-0.5, len(volumes) - 0.5)
    ax_vol.set_xticks([])
    ax_vol.set_ylabel("Volume", fontsize=8)
    ax_vol.tick_params(labelsize=7)

    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)

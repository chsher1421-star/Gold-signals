"""
Free market data via Yahoo Finance (yfinance) - no signup, no API key, no VPN.

Uses COMEX Gold Futures (GC=F) as the data source - this gives REAL exchange-
reported volume (arguably more genuine for VSA than forex/CFD tick-volume,
since it's actual centralized exchange data). Trades ~23 hours a day, 5 days
a week, same as spot gold - closed only on weekends and a short daily
maintenance break.

Note: this is gold FUTURES, not spot XAUUSD - price/candles will be very
closely correlated with spot gold but not pixel-identical to a CFD broker's
chart.

Yahoo Finance doesn't offer native 3-minute or 4-hour bars, so those are
derived by resampling from 1-minute and 1-hour base data respectively.
"""
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

SYMBOL = "GC=F"

# granularity -> (yfinance interval, period to request)
_NATIVE = {
    "M5": ("5m", "5d"),
    "M15": ("15m", "1mo"),
    "H1": ("60m", "1mo"),
}


def _drop_forming_bar(df, bar_minutes):
    """Remove the last row if its bar hasn't fully closed yet."""
    if df.empty:
        return df
    now = datetime.now(timezone.utc)
    last_ts = df.index[-1]
    last_ts = last_ts.tz_localize("UTC") if last_ts.tzinfo is None else last_ts.tz_convert("UTC")
    bin_end = last_ts + pd.Timedelta(minutes=bar_minutes)
    if bin_end > now:
        return df.iloc[:-1]
    return df


def _resample(df, rule, bar_minutes):
    out = df.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return _drop_forming_bar(out, bar_minutes)


def _to_candles(df):
    candles = []
    for ts, row in df.iterrows():
        ts_utc = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        candles.append(
            {
                "time": ts_utc.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
            }
        )
    return candles


def get_candles(granularity, count=60):
    """
    granularity: one of M3, M5, M15, H1, H4
    Returns a list of completed candle dicts, oldest -> newest.
    """
    if granularity == "M3":
        raw = yf.Ticker(SYMBOL).history(period="7d", interval="1m")
        raw = _drop_forming_bar(raw, 1)
        resampled = _resample(raw, "3min", 3)
        return _to_candles(resampled.tail(count))

    if granularity == "H4":
        raw = yf.Ticker(SYMBOL).history(period="1mo", interval="60m")
        raw = _drop_forming_bar(raw, 60)
        resampled = _resample(raw, "4h", 240)
        return _to_candles(resampled.tail(count))

    if granularity not in _NATIVE:
        raise ValueError(f"Unsupported granularity: {granularity}")

    interval, period = _NATIVE[granularity]
    bar_minutes = {"5m": 5, "15m": 15, "60m": 60}[interval]
    raw = yf.Ticker(SYMBOL).history(period=period, interval=interval)
    raw = _drop_forming_bar(raw, bar_minutes)
    return _to_candles(raw.tail(count))

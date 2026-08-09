"""
Oanda v20 REST API client.
Fetches candle (OHLCV) data for a given instrument and granularity.
Only requires a free demo (practice) account token - no live money needed.
"""
import os
import requests

OANDA_ENV = os.environ.get("OANDA_ENV", "practice")  # "practice" or "live"
OANDA_TOKEN = os.environ.get("OANDA_TOKEN", "")

BASE_URL = (
    "https://api-fxpractice.oanda.com"
    if OANDA_ENV == "practice"
    else "https://api-fxtrade.oanda.com"
)


def get_candles(instrument="XAU_USD", granularity="H4", count=60):
    """
    Returns a list of completed candles (oldest -> newest), each a dict with:
    time, open, high, low, close, volume
    Incomplete (still forming) candles are excluded.
    """
    if not OANDA_TOKEN:
        raise RuntimeError("OANDA_TOKEN environment variable is not set")

    url = f"{BASE_URL}/v3/instruments/{instrument}/candles"
    headers = {"Authorization": f"Bearer {OANDA_TOKEN}"}
    params = {
        "granularity": granularity,
        "count": count,
        "price": "M",  # mid prices
    }
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    candles = []
    for c in data.get("candles", []):
        if not c.get("complete", False):
            continue  # skip the still-forming candle
        candles.append(
            {
                "time": c["time"],
                "open": float(c["mid"]["o"]),
                "high": float(c["mid"]["h"]),
                "low": float(c["mid"]["l"]),
                "close": float(c["mid"]["c"]),
                "volume": int(c["volume"]),
            }
        )
    return candles

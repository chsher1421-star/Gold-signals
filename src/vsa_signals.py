"""
VSA signal detection: No Demand / No Supply / CAB (Climactic Action Bar).

Rules as confirmed by Jerry:

No Demand / No Supply (checked only on the timeframes passed to it, e.g. H4):
  - volume < previous 2 candles' volume (strictly less than BOTH)
  - spread (high-low) is small OR average (i.e. NOT wide) vs recent average
  - close position within the bar is NOT filtered - both flagged, user verifies manually
  - No Demand and No Supply share the exact same numeric condition (per Jerry's
    explicit instruction) - both are reported together as one combined signal.

CAB (checked on M3, M5, M15, H1, H4):
  - volume > 1.5x average volume of previous 10 bars, AND/OR > 1.5x average of
    previous 15 bars (both windows are checked and reported separately since
    Jerry wants to compare) - THIS is the real filter/condition
  - spread is compared against both the 10-bar and 15-bar average range and
    labeled wide/narrow - this is INFORMATIONAL ONLY, not a filter. A high-volume
    narrow-spread bar (effort absorbed, no result) is just as valid a CAB as a
    high-volume wide-spread bar - both are flagged, neither is excluded.
  - close position is irrelevant
"""

REF_RANGE_WINDOW = 10   # bars used to compute "average spread" reference for No Demand/No Supply
SPREAD_SLACK = 1.1      # small/average threshold = up to 10% above the average range (used by No Demand/No Supply)
CAB_VOLUME_MULT = 1.5   # CAB volume must exceed this multiple of the average


def _spread(candle):
    return candle["high"] - candle["low"]


def _avg_range(candles, n):
    window = candles[-n:]
    if not window:
        return 0.0
    return sum(_spread(c) for c in window) / len(window)


def _avg_volume(candles, n):
    window = candles[-n:]
    if not window:
        return 0.0
    return sum(c["volume"] for c in window) / len(window)


def check_no_demand_no_supply(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Returns a list with 0 or 1 signal dicts.
    """
    signals = []
    if len(candles) < REF_RANGE_WINDOW + 3:
        return signals

    current = candles[-1]
    prev1 = candles[-2]
    prev2 = candles[-3]

    history_before_current = candles[:-1]
    ref_range = _avg_range(history_before_current, REF_RANGE_WINDOW)
    spread = _spread(current)

    volume_condition = (
        current["volume"] < prev1["volume"] and current["volume"] < prev2["volume"]
    )
    spread_condition = spread <= ref_range * SPREAD_SLACK

    if volume_condition and spread_condition:
        signals.append(
            {
                "type": "No Demand / No Supply",
                "candle": current,
                "detail": (
                    f"vol={current['volume']} (prev1={prev1['volume']}, "
                    f"prev2={prev2['volume']}) | spread={spread:.2f} "
                    f"(avg_ref={ref_range:.2f})"
                ),
            }
        )
    return signals


def check_cab(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Returns a list with 0 or 1 signal dicts (may report both 10-bar and 15-bar
    windows together if both trigger).
    """
    signals = []
    if len(candles) < 16:
        return signals

    current = candles[-1]
    history_before_current = candles[:-1]

    avg_vol_10 = _avg_volume(history_before_current, 10)
    avg_vol_15 = _avg_volume(history_before_current, 15)
    ref_range_10 = _avg_range(history_before_current, 10)
    ref_range_15 = _avg_range(history_before_current, 15)
    spread = _spread(current)
    # Use the average of the two reference windows to label wide/narrow -
    # informational only, does NOT gate whether a CAB signal fires.
    ref_range = (ref_range_10 + ref_range_15) / 2
    spread_label = "wide" if spread > ref_range else "narrow"

    triggered = []
    if current["volume"] > avg_vol_10 * CAB_VOLUME_MULT:
        triggered.append("10-bar")
    if current["volume"] > avg_vol_15 * CAB_VOLUME_MULT:
        triggered.append("15-bar")

    # Volume is the only real filter. Spread (wide OR narrow) is always valid -
    # a high-volume narrow-spread bar (effort absorbed) is just as much a CAB
    # as a high-volume wide-spread bar, so it is never excluded here.
    if triggered:
        signals.append(
            {
                "type": f"CAB ({'/'.join(triggered)} vol, {spread_label} spread)",
                "candle": current,
                "detail": (
                    f"vol={current['volume']} (avg10={avg_vol_10:.0f}, "
                    f"avg15={avg_vol_15:.0f}, threshold={CAB_VOLUME_MULT}x) | "
                    f"spread={spread:.2f} (avg_ref={ref_range:.2f}, {spread_label})"
                ),
            }
        )
    return signals

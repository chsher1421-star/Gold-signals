"""
VSA signal detection: No Demand / No Supply / CAB / Spring / Upthrust / Test.

Rules as confirmed by Jerry:

No Demand / No Supply (checked only on the timeframes passed to it, e.g. H4):
  - volume < previous 2 candles' volume (strictly less than BOTH)
  - spread (high-low) is small OR average (i.e. NOT wide) vs recent average
  - close position within the bar is NOT filtered - both flagged, user verifies manually
  - No Demand and No Supply share the exact same numeric condition (per Jerry's
    explicit instruction) - both are reported together as one combined signal.

CAB (checked on M3, M5, M15, H1, H4):
  - Volume is measured against SMA(volume, 14) of the previous 14 bars - same
    baseline as the "Relative Volume [ND]" Pine Script indicator (by Sajid
    Khan Ghori) that Jerry uses on TradingView, so the alert and the chart
    indicator always agree on the same number.
  - Tiers (same multiples as that indicator's bands): 1.9x = "high",
    2.2x = "very high", 3.5x = "ultra high".
  - A CAB signal ONLY fires on "very high" (>= 2.2x) or "ultra high"
    (>= 3.5x) volume. "high" (1.9x-2.2x) and below does NOT fire - this is a
    deliberate tightening per Jerry's instruction, replacing the old
    1.4x/2.0x wide/narrow-spread thresholds.
  - spread wide/narrow label is still recorded for information in the alert
    detail line, but it no longer decides the volume threshold - only the
    SMA(14) ratio does.
  - close position is irrelevant

Spring (bullish reversal, checked on M3, M5, M15, H1, H4):
  - current bar's low breaks BELOW the low of the previous SPRING_LOOKBACK bars
  - but the bar closes back up in the upper third of its own range
  - on volume > 1.5x average (10-bar and/or 15-bar)
  - shows sellers pushed to a new low but were absorbed - professionals buying

Upthrust (bearish reversal, checked on M3, M5, M15, H1, H4):
  - mirror of Spring: current bar's high breaks ABOVE the high of the previous
    SPRING_LOOKBACK bars, but closes back down in the lower third of its range,
    on volume > 1.5x average - shows buyers were absorbed, professionals selling

Test (bullish confirmation, checked on M3, M5, M15, H1, H4):
  - current bar's low retests (or lies within a small tolerance of) the low of
    the previous SPRING_LOOKBACK bars
  - on LOW volume (below 10-bar average) and NARROW spread
  - closes back up in the upper third of its own range
  - shows sellers are exhausted at that level (no supply left)
"""

REF_RANGE_WINDOW = 10          # bars used to compute "average spread" reference for No Demand/No Supply
SPREAD_SLACK = 1.1             # small/average threshold = up to 10% above the average range (used by No Demand/No Supply)

# CAB volume tiers - matched to the "Relative Volume [ND]" Pine Script
# indicator (SMA(volume,14) baseline, bands at 1.9x/2.2x/3.5x). Only
# "very high" and "ultra high" fire a CAB signal; "high" (1.9x-2.2x) does not.
CAB_SMA_WINDOW = 14
CAB_HIGH_MULT = 1.9            # indicator's middle band - informational only, does NOT fire a CAB
CAB_VERY_HIGH_MULT = 2.2       # indicator's high band - fires CAB, labeled "very high"
CAB_ULTRA_HIGH_MULT = 3.5      # indicator's highest band - fires CAB, labeled "ultra high"

SPRING_LOOKBACK = 20           # bars used to define a "new low/high" for Spring/Upthrust/Test
SPRING_VOLUME_MULT = 1.5       # Spring/Upthrust volume must exceed this multiple of the average
CLOSE_UPPER_THIRD = 0.66       # close position (0-1 within the bar's range) counted as "closing strong"
CLOSE_LOWER_THIRD = 0.33       # close position counted as "closing weak"


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


def _volume_tier(current_volume, sma14):
    """
    Returns (ratio, tier) where tier is one of:
    "ultra high" (>= 3.5x), "very high" (>= 2.2x), "high" (>= 1.9x), or None
    (below the "high" band - not climactic at all).
    Mirrors the "Relative Volume [ND]" Pine Script indicator's bands exactly.
    """
    if sma14 <= 0:
        return 0.0, None

    ratio = current_volume / sma14

    if ratio >= CAB_ULTRA_HIGH_MULT:
        return ratio, "ultra high"
    if ratio >= CAB_VERY_HIGH_MULT:
        return ratio, "very high"
    if ratio >= CAB_HIGH_MULT:
        return ratio, "high"
    return ratio, None


def _close_position(candle):
    """
    Returns where the close sits within the bar's own high-low range,
    as a value from 0.0 (closed at the low) to 1.0 (closed at the high).
    """
    rng = candle["high"] - candle["low"]
    if rng == 0:
        return 0.5
    return (candle["close"] - candle["low"]) / rng


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


def candle_diagnostics(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Returns diagnostic numbers for the LAST candle in the list (volume vs
    10/15-bar average, spread vs average range, close position) - used for
    verbose per-run logging so every candle's numbers are visible even when
    no signal fires, making it possible to check a "missed" signal later
    without needing to re-derive it from a chart screenshot.
    """
    if len(candles) < 2:
        return {}

    current = candles[-1]
    history_before_current = candles[:-1]

    avg_vol_10 = _avg_volume(history_before_current, 10)
    avg_vol_15 = _avg_volume(history_before_current, 15)
    ref_range_10 = _avg_range(history_before_current, 10)
    ref_range_15 = _avg_range(history_before_current, 15)
    ref_range = (ref_range_10 + ref_range_15) / 2
    spread = _spread(current)
    spread_label = "wide" if spread > ref_range else "narrow"

    sma_vol_14 = _avg_volume(history_before_current, CAB_SMA_WINDOW)
    vol_ratio_14, vol_tier = _volume_tier(current["volume"], sma_vol_14)

    return {
        "time": current["time"],
        "volume": current["volume"],
        "avg_vol_10": avg_vol_10,
        "avg_vol_15": avg_vol_15,
        "spread": spread,
        "ref_range": ref_range,
        "spread_label": spread_label,
        "close_pos": _close_position(current),
        "sma_vol_14": sma_vol_14,
        "vol_ratio_14": vol_ratio_14,
        "vol_tier": vol_tier or "below high",
    }


def check_cab(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Volume is measured against SMA(volume, 14) - same baseline as the
    "Relative Volume [ND]" Pine Script indicator. Only fires when the
    current bar's volume reaches the "very high" (>= 2.2x) or "ultra high"
    (>= 3.5x) band; "high" (1.9x-2.2x) and below no longer fire a CAB.
    Returns a list with 0 or 1 signal dicts.
    """
    signals = []
    if len(candles) < CAB_SMA_WINDOW + 1:
        return signals

    current = candles[-1]
    history_before_current = candles[:-1]

    sma_vol_14 = _avg_volume(history_before_current, CAB_SMA_WINDOW)
    ratio, tier = _volume_tier(current["volume"], sma_vol_14)

    # spread label kept only as information in the alert detail - it no
    # longer decides the threshold.
    ref_range_10 = _avg_range(history_before_current, 10)
    ref_range_15 = _avg_range(history_before_current, 15)
    ref_range = (ref_range_10 + ref_range_15) / 2
    spread = _spread(current)
    spread_label = "wide" if spread > ref_range else "narrow"

    if tier in ("very high", "ultra high"):
        signals.append(
            {
                "type": f"CAB ({tier} vol, {spread_label} spread)",
                "candle": current,
                "tier": tier,
                "detail": (
                    f"vol={current['volume']} (sma14={sma_vol_14:.0f}, "
                    f"ratio={ratio:.2f}x, tier={tier}) | "
                    f"spread={spread:.2f} (avg_ref={ref_range:.2f}, {spread_label})"
                ),
            }
        )
    return signals


def check_spring(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Spring: new low vs previous SPRING_LOOKBACK bars, closes back up strong,
    on high volume. Returns a list with 0 or 1 signal dicts.
    """
    signals = []
    if len(candles) < SPRING_LOOKBACK + 1:
        return signals

    current = candles[-1]
    history = candles[-(SPRING_LOOKBACK + 1):-1]

    prior_low = min(c["low"] for c in history)
    avg_vol_10 = _avg_volume(candles[:-1], 10)
    avg_vol_15 = _avg_volume(candles[:-1], 15)
    close_pos = _close_position(current)

    new_low = current["low"] < prior_low
    closes_strong = close_pos >= CLOSE_UPPER_THIRD

    triggered = []
    if current["volume"] > avg_vol_10 * SPRING_VOLUME_MULT:
        triggered.append("10-bar")
    if current["volume"] > avg_vol_15 * SPRING_VOLUME_MULT:
        triggered.append("15-bar")

    if new_low and closes_strong and triggered:
        signals.append(
            {
                "type": f"Spring ({'/'.join(triggered)} vol)",
                "candle": current,
                "detail": (
                    f"low={current['low']:.2f} broke prior "
                    f"{SPRING_LOOKBACK}-bar low={prior_low:.2f} | "
                    f"close_pos={close_pos:.2f} (upper-third) | "
                    f"vol={current['volume']} (avg10={avg_vol_10:.0f}, "
                    f"avg15={avg_vol_15:.0f}, threshold={SPRING_VOLUME_MULT}x)"
                ),
            }
        )
    return signals


def check_upthrust(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Upthrust: mirror of Spring - new high, closes back down weak, on high
    volume. Returns a list with 0 or 1 signal dicts.
    """
    signals = []
    if len(candles) < SPRING_LOOKBACK + 1:
        return signals

    current = candles[-1]
    history = candles[-(SPRING_LOOKBACK + 1):-1]

    prior_high = max(c["high"] for c in history)
    avg_vol_10 = _avg_volume(candles[:-1], 10)
    avg_vol_15 = _avg_volume(candles[:-1], 15)
    close_pos = _close_position(current)

    new_high = current["high"] > prior_high
    closes_weak = close_pos <= CLOSE_LOWER_THIRD

    triggered = []
    if current["volume"] > avg_vol_10 * SPRING_VOLUME_MULT:
        triggered.append("10-bar")
    if current["volume"] > avg_vol_15 * SPRING_VOLUME_MULT:
        triggered.append("15-bar")

    if new_high and closes_weak and triggered:
        signals.append(
            {
                "type": f"Upthrust ({'/'.join(triggered)} vol)",
                "candle": current,
                "detail": (
                    f"high={current['high']:.2f} broke prior "
                    f"{SPRING_LOOKBACK}-bar high={prior_high:.2f} | "
                    f"close_pos={close_pos:.2f} (lower-third) | "
                    f"vol={current['volume']} (avg10={avg_vol_10:.0f}, "
                    f"avg15={avg_vol_15:.0f}, threshold={SPRING_VOLUME_MULT}x)"
                ),
            }
        )
    return signals


def check_test(candles):
    """
    candles: list of completed candles, oldest -> newest.
    Evaluates only the LAST candle in the list.
    Test: retest of a prior SPRING_LOOKBACK-bar low on LOW volume + narrow
    spread, closing back up strong. Returns a list with 0 or 1 signal dicts.
    """
    signals = []
    if len(candles) < SPRING_LOOKBACK + 1:
        return signals

    current = candles[-1]
    history = candles[-(SPRING_LOOKBACK + 1):-1]

    prior_low = min(c["low"] for c in history)
    avg_vol_10 = _avg_volume(candles[:-1], 10)
    ref_range = _avg_range(candles[:-1], REF_RANGE_WINDOW)
    spread = _spread(current)
    close_pos = _close_position(current)

    near_prior_low = current["low"] <= prior_low + (ref_range * 0.1)
    low_volume = current["volume"] < avg_vol_10
    narrow_spread = spread <= ref_range
    closes_strong = close_pos >= CLOSE_UPPER_THIRD

    if near_prior_low and low_volume and narrow_spread and closes_strong:
        signals.append(
            {
                "type": "Test",
                "candle": current,
                "detail": (
                    f"low={current['low']:.2f} retested prior "
                    f"{SPRING_LOOKBACK}-bar low={prior_low:.2f} | "
                    f"vol={current['volume']} (avg10={avg_vol_10:.0f}, "
                    f"low-volume) | spread={spread:.2f} "
                    f"(avg_ref={ref_range:.2f}, narrow) | "
                    f"close_pos={close_pos:.2f}"
                ),
            }
        )
    return signals

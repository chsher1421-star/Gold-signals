"""
Main entry point. Run every 5 minutes by GitHub Actions.

For each timeframe:
  1. Fetch fresh candles from Yahoo Finance (Gold Futures, free, no signup)
  2. Run the relevant signal checks (CAB on all TFs, No Demand/No Supply on H4 only)
  3. Skip anything already alerted (tracked in state.json)
  4. For new signals: generate a chart image + send notification
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from market_data import get_candles
from vsa_signals import check_cab, check_no_demand_no_supply
from chart_gen import generate_chart
from notifier import notify
from state_manager import already_alerted, load_state, mark_alerted, save_state

SYMBOL_LABEL = "GOLD (COMEX Futures - GC=F)"
CAB_TIMEFRAMES = ["M3", "M5", "M15", "H1", "H4"]
NO_DEMAND_SUPPLY_TIMEFRAMES = ["H4"]

PKT_OFFSET = timedelta(hours=5)  # Pakistan Standard Time = UTC+5, no DST


def to_pkt_str(utc_time_str):
    dt = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00"))
    pkt = dt.replace(tzinfo=None) + PKT_OFFSET
    return pkt.strftime("%Y-%m-%d %H:%M") + " PKT"


def process_timeframe(granularity, state):
    do_cab = granularity in CAB_TIMEFRAMES
    do_ndns = granularity in NO_DEMAND_SUPPLY_TIMEFRAMES

    try:
        candles = get_candles(granularity, count=60)
    except Exception as e:
        print(f"[{granularity}] failed to fetch candles: {e}")
        return

    if len(candles) < 20:
        print(f"[{granularity}] not enough candle history yet ({len(candles)})")
        return

    found = []
    if do_cab:
        found += check_cab(candles)
    if do_ndns:
        found += check_no_demand_no_supply(candles)

    for sig in found:
        candle_time = sig["candle"]["time"]
        sig_type = sig["type"]

        if already_alerted(state, granularity, sig_type, candle_time):
            continue

        print(f"[{granularity}] NEW signal: {sig_type} at {candle_time} | {sig['detail']}")

        safe_time = candle_time.replace(":", "-")
        chart_path = f"/tmp/signal_{granularity}_{safe_time}.png"
        title = f"GOLD (GC) {granularity} - {sig_type}"
        try:
            generate_chart(candles, candle_time, title, chart_path)
        except Exception as e:
            print(f"chart generation failed: {e}")
            chart_path = None

        message = (
            f"Symbol: {SYMBOL_LABEL}\n"
            f"Timeframe: {granularity}\n"
            f"Candle: {to_pkt_str(candle_time)}\n"
            f"Signal: {sig_type}\n"
            f"{sig['detail']}"
        )
        notify(f"Gold Signal: {sig_type} [{granularity}]", message, chart_path)
        mark_alerted(state, granularity, sig_type, candle_time)


def main():
    state = load_state()
    all_timeframes = sorted(set(CAB_TIMEFRAMES + NO_DEMAND_SUPPLY_TIMEFRAMES))
    for tf in all_timeframes:
        process_timeframe(tf, state)
    save_state(state)


if __name__ == "__main__":
    main()

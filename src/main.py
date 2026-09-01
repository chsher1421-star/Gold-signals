"""
Main entry point for the Gold VSA Alert System.

Runs from GitHub Actions.

For each configured timeframe:
  1. Fetch completed XAUUSD candles from Pepperstone cTrader.
  2. Run CAB and/or No Demand / No Supply checks.
  3. Skip signals already stored in state.json.
  4. Generate a chart and send notifications for new signals.
  5. Fail the workflow when market-data retrieval fails.

The VSA rules themselves remain in vsa_signals.py.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(
    0,
    os.path.dirname(__file__),
)


from market_data import get_candles
from vsa_signals import (
    check_cab,
    check_no_demand_no_supply,
    check_spring,
    check_upthrust,
    check_test,
    candle_diagnostics,
)


def _last_n_slices(candles, n=3):
    """
    Returns up to n progressively-larger prefixes of `candles`, each one
    ending at one of the last n candles - oldest of the three first, the
    true latest candle last. Feeding each slice into a check_*() function
    makes it evaluate that slice's last candle "as if" it were the newest
    completed candle, using only the history available up to that point.
    """
    slices = []
    total = len(candles)

    for offset in range(n, 0, -1):
        idx = total - offset

        if idx < 0:
            continue

        slices.append(
            candles[: idx + 1]
        )

    return slices


def check_last_n(check_fn, candles, n=3):
    """
    Runs check_fn against each of the last n candles (not just the very
    latest one). This is a safety net: if a prior run timed out or failed
    and never evaluated a candle while it was "the latest", this run will
    still catch it. Duplicate notifications are prevented separately by
    already_alerted()/state.json, which key on the candle's own timestamp.
    """
    results = []

    for sub in _last_n_slices(candles, n):
        results.extend(
            check_fn(sub)
        )

    return results


def log_diagnostics(granularity, candles, n=3):
    """
    Prints volume/spread numbers for the last n candles on every run,
    whether or not a signal fired, so a "why didn't this trigger" question
    can be answered directly from the workflow log instead of needing a
    chart screenshot.
    """
    for sub in _last_n_slices(candles, n):
        diag = candle_diagnostics(sub)

        if not diag:
            continue

        print(
            f"[{granularity}] diag "
            f"{diag['time']}: "
            f"vol={diag['volume']} "
            f"(avg10={diag['avg_vol_10']:.0f}, "
            f"avg15={diag['avg_vol_15']:.0f}, "
            f"sma14={diag['sma_vol_14']:.0f}, "
            f"ratio14={diag['vol_ratio_14']:.2f}x, "
            f"tier={diag['vol_tier']}) | "
            f"spread={diag['spread']:.2f} "
            f"(avg_ref={diag['ref_range']:.2f}, "
            f"{diag['spread_label']}) | "
            f"close_pos={diag['close_pos']:.2f}"
        )
from chart_gen import generate_chart
from notifier import notify
from state_manager import (
    already_alerted,
    load_state,
    mark_alerted,
    save_state,
)


SYMBOL_LABEL = (
    "GOLD (Pepperstone cTrader XAUUSD)"
)

CAB_TIMEFRAMES = [
    "M3",
    "M5",
    "M15",
    "H1",
    "H4",
]

NO_DEMAND_SUPPLY_TIMEFRAMES = [
    "H4",
]

PKT_OFFSET = timedelta(
    hours=5
)

SUMMARY_HOUR_PKT = 23


def to_pkt_str(
    utc_time_str: str,
) -> str:
    """
    Convert an ISO UTC candle timestamp into
    Pakistan Standard Time.
    """
    dt = datetime.fromisoformat(
        utc_time_str.replace(
            "Z",
            "+00:00",
        )
    )

    pkt = (
        dt.astimezone(
            timezone(
                timedelta(hours=5)
            )
        )
    )

    return pkt.strftime(
        "%Y-%m-%d %H:%M"
    ) + " PKT"


def get_pkt_now() -> datetime:
    """
    Return the current time in PKT.
    """
    return datetime.now(
        timezone(
            timedelta(hours=5)
        )
    )


def is_market_closed(
    now_pkt: datetime,
) -> bool:
    """
    Gold/Forex CFD markets close roughly
    Friday ~9-10 PM UTC (~Saturday 2-3 AM PKT)
    and reopen Sunday ~9-10 PM UTC
    (~Monday 2-3 AM PKT).

    In PKT terms that means: all of Saturday,
    all of Sunday, and early Monday morning
    (before ~3 AM) are closed.

    weekday(): Monday=0 ... Saturday=5, Sunday=6
    """
    weekday = now_pkt.weekday()

    if weekday == 5:
        # Saturday - closed all day
        return True

    if weekday == 6:
        # Sunday - closed all day
        return True

    if weekday == 0 and now_pkt.hour < 3:
        # Early Monday before reopen
        return True

    return False


def ensure_daily_stats(
    state: dict,
) -> dict:
    """
    Ensure daily statistics belong to today.
    """
    today_str = get_pkt_now().strftime(
        "%Y-%m-%d"
    )

    stats = state.get(
        "daily_stats"
    )

    if (
        not stats
        or stats.get("date")
        != today_str
    ):
        stats = {
            "date": today_str,
            "checks": 0,
            "signals": 0,
            "summary_sent": False,
        }

        state[
            "daily_stats"
        ] = stats

    return stats


def record_check(
    state: dict,
) -> None:
    stats = ensure_daily_stats(
        state
    )

    stats["checks"] += 1


def record_signal(
    state: dict,
) -> None:
    stats = ensure_daily_stats(
        state
    )

    stats["signals"] += 1


def maybe_send_daily_summary(
    state: dict,
) -> None:
    """
    Send the daily system summary around
    11 PM PKT.
    """
    stats = ensure_daily_stats(
        state
    )

    now = get_pkt_now()

    if (
        now.hour
        == SUMMARY_HOUR_PKT
        and not stats.get(
            "summary_sent"
        )
    ):
        message = (
            f"Date: {stats['date']}\n"
            f"Checks run today: "
            f"{stats['checks']}\n"
            f"Signals found today: "
            f"{stats['signals']}\n\n"
            f"System is running normally."
        )

        notify(
            "Gold VSA - Daily Summary",
            message,
        )

        stats[
            "summary_sent"
        ] = True


def process_timeframe(
    granularity: str,
    state: dict,
) -> list[str]:
    """
    Process one timeframe.

    Returns a list of error messages instead
    of silently hiding market-data failures.
    """
    do_cab = (
        granularity
        in CAB_TIMEFRAMES
    )

    do_ndns = (
        granularity
        in NO_DEMAND_SUPPLY_TIMEFRAMES
    )

    errors: list[str] = []

    try:
        candles = get_candles(
            granularity,
            count=60,
        )

    except Exception as exc:
        message = (
            f"[{granularity}] failed "
            f"to fetch candles: {exc}"
        )

        print(
            message,
            file=sys.stderr,
        )

        errors.append(
            message
        )

        return errors

    if len(candles) < 25:
        message = (
            f"[{granularity}] not enough "
            f"completed candle history: "
            f"{len(candles)}"
        )

        print(
            message,
            file=sys.stderr,
        )

        errors.append(
            message
        )

        return errors

    found = []

    if do_cab:
        log_diagnostics(
            granularity,
            candles,
        )

        found.extend(
            check_last_n(
                check_cab,
                candles,
            )
        )

        found.extend(
            check_last_n(
                check_spring,
                candles,
            )
        )

        found.extend(
            check_last_n(
                check_upthrust,
                candles,
            )
        )

        found.extend(
            check_last_n(
                check_test,
                candles,
            )
        )

    if do_ndns:
        found.extend(
            check_last_n(
                check_no_demand_no_supply,
                candles,
            )
        )

    if not found:
        print(
            f"[{granularity}] "
            "No new VSA signals."
        )

        return errors

    for sig in found:
        candle = sig.get(
            "candle",
            {}
        )

        candle_time = candle.get(
            "time"
        )

        sig_type = sig.get(
            "type",
            "Unknown",
        )

        if not candle_time:
            message = (
                f"[{granularity}] signal "
                "did not contain a "
                "candle timestamp."
            )

            print(
                message,
                file=sys.stderr,
            )

            errors.append(
                message
            )

            continue

        if already_alerted(
            state,
            granularity,
            sig_type,
            candle_time,
        ):
            print(
                f"[{granularity}] "
                f"Already alerted: "
                f"{sig_type} "
                f"at {candle_time}"
            )

            continue

        detail = sig.get(
            "detail",
            "",
        )

        print(
            f"[{granularity}] NEW signal: "
            f"{sig_type} at "
            f"{candle_time} | "
            f"{detail}"
        )

        safe_time = (
            candle_time
            .replace(
                ":",
                "-"
            )
            .replace(
                "Z",
                ""
            )
        )

        chart_path = (
            f"/tmp/"
            f"signal_"
            f"{granularity}_"
            f"{safe_time}.png"
        )

        title = (
            f"GOLD "
            f"{granularity} - "
            f"{sig_type}"
        )

        try:
            generate_chart(
                candles,
                candle_time,
                title,
                chart_path,
                show_volume_bands=sig_type.startswith(
                    "CAB"
                ),
            )

        except Exception as exc:
            message = (
                f"[{granularity}] "
                f"chart generation failed: "
                f"{exc}"
            )

            print(
                message,
                file=sys.stderr,
            )

            chart_path = None

            errors.append(
                message
            )

        message = (
            f"Symbol: "
            f"{SYMBOL_LABEL}\n"
            f"Timeframe: "
            f"{granularity}\n"
            f"Candle: "
            f"{to_pkt_str(candle_time)}\n"
            f"Signal: "
            f"{sig_type}\n"
            f"{detail}"
        )

        try:
            notify(
                (
                    "Gold Signal: "
                    f"{sig_type} "
                    f"[{granularity}]"
                ),
                message,
                chart_path,
            )

        except Exception as exc:
            error_message = (
                f"[{granularity}] "
                f"notification failed: "
                f"{exc}"
            )

            print(
                error_message,
                file=sys.stderr,
            )

            errors.append(
                error_message
            )

            continue

        mark_alerted(
            state,
            granularity,
            sig_type,
            candle_time,
        )

        record_signal(
            state
        )

    return errors


def main() -> None:
    state = load_state()

    now_pkt = get_pkt_now()

    if is_market_closed(now_pkt):
        print(
            "Market is closed "
            "(weekend) - skipping "
            "candle checks."
        )

        maybe_send_daily_summary(
            state
        )

        save_state(
            state
        )

        return

    record_check(
        state
    )

    all_timeframes = list(
        dict.fromkeys(
            CAB_TIMEFRAMES
            + NO_DEMAND_SUPPLY_TIMEFRAMES
        )
    )

    all_errors: list[str] = []

    print(
        "Starting Gold VSA check..."
    )

    print(
        f"Timeframes: "
        f"{', '.join(all_timeframes)}"
    )

    for timeframe in all_timeframes:
        errors = process_timeframe(
            timeframe,
            state,
        )

        all_errors.extend(
            errors
        )

    maybe_send_daily_summary(
        state
    )

    save_state(
        state
    )

    if all_errors:
        error_text = "\n".join(
            f"- {error}"
            for error in all_errors
        )

        raise RuntimeError(
            "Gold VSA check completed "
            "with errors:\n"
            f"{error_text}"
        )

    print(
        "Gold VSA check completed "
        "successfully."
    )


if __name__ == "__main__":
    main()

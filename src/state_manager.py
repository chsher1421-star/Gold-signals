"""
Tracks which (timeframe, signal_type, candle_time) combos have already
been alerted, so the same signal doesn't get sent again on the next run.
State is stored in state.json and committed back to the repo by the
GitHub Actions workflow after every run.
"""
import json
import os

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state.json")
MAX_HISTORY_PER_KEY = 100


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _key(granularity, signal_type):
    return f"{granularity}:{signal_type}"


def already_alerted(state, granularity, signal_type, candle_time):
    return candle_time in state.get(_key(granularity, signal_type), [])


def mark_alerted(state, granularity, signal_type, candle_time):
    k = _key(granularity, signal_type)
    history = state.setdefault(k, [])
    history.append(candle_time)
    state[k] = history[-MAX_HISTORY_PER_KEY:]

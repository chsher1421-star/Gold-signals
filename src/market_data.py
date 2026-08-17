"""
Pepperstone cTrader Open API market-data layer.

Replaces Yahoo Finance (GC=F) with Pepperstone's cTrader feed.

Important:
- cTrader natively supports M3, M5, M15, H1 and H4 trendbars.
- Trendbars include tick volume.
- We fetch all required timeframes in ONE cTrader TCP session per GitHub run.
- Only completed candles are returned.
- Access tokens are refreshed automatically near expiry.
"""
from __future__ import annotations

import base64
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from nacl import encoding, public
from twisted.internet import reactor

from ctrader_open_api import Client, Protobuf, EndPoints, TcpProtocol
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *


SYMBOL_NAME = os.environ.get("CTRADER_SYMBOL_NAME", "XAUUSD")
ACCOUNT_ID = int(os.environ["CTRADER_ACCOUNT_ID"])
ENVIRONMENT = os.environ.get("CTRADER_ENVIRONMENT", "demo").lower()

CLIENT_ID = os.environ["CTRADER_CLIENT_ID"]
CLIENT_SECRET = os.environ["CTRADER_CLIENT_SECRET"]
ACCESS_TOKEN = os.environ["CTRADER_ACCESS_TOKEN"]
REFRESH_TOKEN = os.environ["CTRADER_REFRESH_TOKEN"]
TOKEN_EXPIRES_AT = int(os.environ.get("CTRADER_TOKEN_EXPIRES_AT", "0"))

GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "chsher1421-star")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Gold-signals")

REFRESH_BUFFER_SECONDS = 7 * 24 * 60 * 60

TF_MINUTES = {
    "M3": 3,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
}

# Cache for this single Python process.
_ALL_CANDLES: dict[str, list[dict[str, Any]]] | None = None


def _token_needs_refresh() -> bool:
    if TOKEN_EXPIRES_AT <= 0:
        return True
    return int(time.time()) >= TOKEN_EXPIRES_AT - REFRESH_BUFFER_SECONDS


def _refresh_access_token() -> tuple[str, str, int]:
    url = "https://openapi.ctrader.com/apps/token"
    params = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    response = requests.post(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("errorCode"):
        raise RuntimeError(
            f"cTrader token refresh failed: {data.get('errorCode')} - "
            f"{data.get('description')}"
        )

    expires_in = int(data["expiresIn"])
    return (
        data["accessToken"],
        data["refreshToken"],
        int(time.time()) + expires_in,
    )


def _update_github_secret(name: str, value: str) -> None:
    """Write one encrypted repository Actions secret via GitHub REST API."""
    if not GITHUB_PAT:
        raise RuntimeError(
            "GITHUB_PAT is required for automatic cTrader token rotation."
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_PAT}",
        "X-GitHub-Api-Version": "2026-03-10",
    }

    public_key_url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        "/actions/secrets/public-key"
    )
    key_response = requests.get(public_key_url, headers=headers, timeout=30)
    key_response.raise_for_status()
    key_data = key_response.json()

    repo_public_key = public.PublicKey(
        base64.b64decode(key_data["key"]),
        encoding.RawEncoder(),
    )
    encrypted_value = public.SealedBox(repo_public_key).encrypt(
        value.encode("utf-8")
    )

    secret_url = (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"
        f"/actions/secrets/{name}"
    )
    payload = {
        "encrypted_value": base64.b64encode(encrypted_value).decode("utf-8"),
        "key_id": key_data["key_id"],
    }

    put_response = requests.put(
        secret_url,
        headers=headers,
        json=payload,
        timeout=30,
    )
    put_response.raise_for_status()


def _maybe_refresh_token() -> None:
    global ACCESS_TOKEN, REFRESH_TOKEN, TOKEN_EXPIRES_AT

    if not _token_needs_refresh():
        return

    print("cTrader access token is near expiry; refreshing...")

    new_access, new_refresh, new_expires_at = _refresh_access_token()

    # Save the new values to GitHub BEFORE replacing in-memory values.
    # This protects against losing the current refresh token if GitHub fails.
    _update_github_secret("CTRADER_ACCESS_TOKEN", new_access)
    _update_github_secret("CTRADER_REFRESH_TOKEN", new_refresh)
    _update_github_secret(
        "CTRADER_TOKEN_EXPIRES_AT",
        str(new_expires_at),
    )

    ACCESS_TOKEN = new_access
    REFRESH_TOKEN = new_refresh
    TOKEN_EXPIRES_AT = new_expires_at

    print("cTrader token refreshed and GitHub secrets updated.")


def _price_from_relative(value: int, digits: int) -> float:
    return round(value / 100000.0, digits)


def _completed_candles(trendbars, digits: int, tf_minutes: int):
    candles = []

    for bar in trendbars:
        low = int(bar.low)
        open_raw = low + int(bar.deltaOpen)
        close_raw = low + int(bar.deltaClose)
        high_raw = low + int(bar.deltaHigh)

        ts = int(bar.utcTimestampInMinutes) * 60
        candles.append(
            {
                "time": datetime.fromtimestamp(
                    ts,
                    tz=timezone.utc,
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "open": _price_from_relative(open_raw, digits),
                "high": _price_from_relative(high_raw, digits),
                "low": _price_from_relative(low, digits),
                "close": _price_from_relative(close_raw, digits),
                "volume": int(bar.volume),
            }
        )

    candles.sort(key=lambda row: row["time"])

    # Remove the currently-forming candle, if present.
    if candles:
        latest_dt = datetime.fromisoformat(
            candles[-1]["time"].replace("Z", "+00:00")
        )
        latest_epoch = int(latest_dt.timestamp())
        current_bucket = (
            int(time.time()) // (tf_minutes * 60)
        ) * (tf_minutes * 60)

        if latest_epoch >= current_bucket:
            candles.pop()

    return candles


def _fetch_all_timeframes() -> dict[str, list[dict[str, Any]]]:
    """
    One TCP session, one authentication chain, one symbol lookup, then
    five trendbar requests. This avoids Twisted reactor restart problems.
    """
    host = (
        EndPoints.PROTOBUF_LIVE_HOST
        if ENVIRONMENT == "live"
        else EndPoints.PROTOBUF_DEMO_HOST
    )
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)

    result_box: dict[str, Any] = {}
    errors: list[str] = []
    pending = set(TF_MINUTES.keys())
    symbol_info: dict[str, int] = {}

    def fail(failure_or_exc):
        errors.append(str(failure_or_exc))
        if reactor.running:
            reactor.stop()

    def send(request, callback):
    deferred = client.send(request)

    def handle_response(message):
        response = Protobuf.extract(message)
        return callback(response)

    deferred.addCallback(handle_response)
    deferred.addErrback(fail)
    return deferred

    def finish_if_done():
        if not pending and reactor.running:
            result_box["value"] = {
                tf: result_box[tf] for tf in TF_MINUTES.keys()
            }
            reactor.stop()

    def after_trendbars(tf: str, response):
        digits = symbol_info["digits"]
        result_box[tf] = _completed_candles(
            response.trendbar,
            digits,
            TF_MINUTES[tf],
        )
        pending.discard(tf)
        finish_if_done()

    def request_trendbars():
        now_ms = int(time.time() * 1000)

        for tf, minutes in TF_MINUTES.items():
            request = ProtoOAGetTrendbarsReq()
            request.ctidTraderAccountId = ACCOUNT_ID
            request.symbolId = symbol_info["symbol_id"]
            request.period = getattr(ProtoOATrendbarPeriod, tf)

            # 250 bars gives enough history for all current VSA lookbacks.
            request.fromTimestamp = now_ms - (
                250 * minutes * 60 * 1000
            )
            request.toTimestamp = now_ms

            send(
                request,
                lambda response, tf=tf: after_trendbars(tf, response),
            )

    def after_symbol_details(response):
        if not response.symbol:
            raise RuntimeError(
                f"No full symbol data returned for symbolId={symbol_info['symbol_id']}."
            )
        symbol_info["digits"] = int(response.symbol[0].digits)
        request_trendbars()

    def request_symbol_details(symbol_id: int):
        request = ProtoOASymbolByIdReq()
        request.ctidTraderAccountId = ACCOUNT_ID
        request.symbolId.append(int(symbol_id))
        send(request, after_symbol_details)

    def after_symbols(response):
        wanted = SYMBOL_NAME.upper().replace("/", "")
        exact = []

        for symbol in response.symbol:
            name = getattr(symbol, "symbolName", "")
            normalized = name.upper().replace("/", "")
            if normalized == wanted:
                exact.append(symbol)

        candidates = exact

        if not candidates:
            for symbol in response.symbol:
                name = getattr(symbol, "symbolName", "")
                normalized = name.upper().replace("/", "")
                if "XAUUSD" in normalized:
                    candidates.append(symbol)

        if not candidates:
            raise RuntimeError(
                f"Could not find {SYMBOL_NAME} on Pepperstone cTrader."
            )

        selected = candidates[0]
        symbol_info["symbol_id"] = int(selected.symbolId)
        print(
            f"Using cTrader symbol: {selected.symbolName} "
            f"(id={symbol_info['symbol_id']})"
        )
        request_symbol_details(symbol_info["symbol_id"])

    def after_account_auth(_response):
        request = ProtoOASymbolsListReq()
        request.ctidTraderAccountId = ACCOUNT_ID
        request.includeArchivedSymbols = False
        send(request, after_symbols)

    def after_app_auth(_response):
        request = ProtoOAAccountAuthReq()
        request.ctidTraderAccountId = ACCOUNT_ID
        request.accessToken = ACCESS_TOKEN
        send(request, after_account_auth)

    def connected(_client):
        request = ProtoOAApplicationAuthReq()
        request.clientId = CLIENT_ID
        request.clientSecret = CLIENT_SECRET
        send(request, after_app_auth)

    def disconnected(_client, reason):
        if not result_box and not errors:
            errors.append(f"cTrader disconnected: {reason}")
        if reactor.running:
            reactor.stop()

    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)

    client.startService()
    reactor.callLater(
        45,
        lambda: (
            errors.append("cTrader request timed out after 45 seconds."),
            reactor.stop(),
        ) if reactor.running else None,
    )

    reactor.run()

    if errors:
        raise RuntimeError(errors[0])

    if "value" not in result_box:
        raise RuntimeError(
            "cTrader returned no market-data result."
        )

    return result_box["value"]


def get_candles(granularity, count=60):
    """
    granularity: M3, M5, M15, H1, H4
    Returns completed candles, oldest -> newest.
    """
    global _ALL_CANDLES

    if granularity not in TF_MINUTES:
        raise ValueError(f"Unsupported granularity: {granularity}")

    if _ALL_CANDLES is None:
        _maybe_refresh_token()
        _ALL_CANDLES = _fetch_all_timeframes()

    return _ALL_CANDLES[granularity][-count:]

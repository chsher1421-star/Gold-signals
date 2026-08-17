"""
Pepperstone cTrader Open API market-data layer.

Fetches completed XAUUSD trendbars for:
M3, M5, M15, H1, H4.

Authentication:
ApplicationAuth -> GetAccountListByAccessToken -> AccountAuth
-> SymbolList -> SymbolById -> Trendbars.

All cTrader responses are unwrapped with Protobuf.extract().
cTrader ProtoOAErrorRes responses are converted into clear errors.
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

from ctrader_open_api import (
    Client,
    Protobuf,
    EndPoints,
    TcpProtocol,
)

from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAAccountAuthReq,
    ProtoOAApplicationAuthReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetTrendbarsReq,
    ProtoOASymbolByIdReq,
    ProtoOASymbolsListReq,
)

from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOATrendbarPeriod,
)


# ============================================================
# CONFIGURATION
# ============================================================

SYMBOL_NAME = os.environ.get(
    "CTRADER_SYMBOL_NAME",
    "XAUUSD",
)

ACCOUNT_ID = int(
    os.environ["CTRADER_ACCOUNT_ID"]
)

ENVIRONMENT = os.environ.get(
    "CTRADER_ENVIRONMENT",
    "demo",
).lower()

CLIENT_ID = os.environ[
    "CTRADER_CLIENT_ID"
]

CLIENT_SECRET = os.environ[
    "CTRADER_CLIENT_SECRET"
]

ACCESS_TOKEN = os.environ[
    "CTRADER_ACCESS_TOKEN"
]

REFRESH_TOKEN = os.environ[
    "CTRADER_REFRESH_TOKEN"
]

TOKEN_EXPIRES_AT = int(
    os.environ.get(
        "CTRADER_TOKEN_EXPIRES_AT",
        "0",
    )
)

GITHUB_PAT = os.environ.get(
    "GITHUB_PAT",
    "",
)

GITHUB_OWNER = os.environ.get(
    "GITHUB_OWNER",
    "chsher1421-star",
)

GITHUB_REPO = os.environ.get(
    "GITHUB_REPO",
    "Gold-signals",
)

# Refresh one week before expiry.
REFRESH_BUFFER_SECONDS = (
    7 * 24 * 60 * 60
)


TF_MINUTES = {
    "M3": 3,
    "M5": 5,
    "M15": 15,
    "H1": 60,
    "H4": 240,
}


_ALL_CANDLES: (
    dict[str, list[dict[str, Any]]] | None
) = None


# ============================================================
# TOKEN REFRESH
# ============================================================

def _token_needs_refresh() -> bool:
    """
    Return True when the access token is expired,
    near expiry, or when no expiry timestamp exists.
    """
    if TOKEN_EXPIRES_AT <= 0:
        return True

    return (
        int(time.time())
        >= (
            TOKEN_EXPIRES_AT
            - REFRESH_BUFFER_SECONDS
        )
    )


def _refresh_access_token() -> tuple[
    str,
    str,
    int,
]:
    """
    Refresh the cTrader access token.

    Returns:
        new_access_token,
        new_refresh_token,
        new_expiry_unix_timestamp
    """
    url = (
        "https://openapi.ctrader.com/apps/token"
    )

    params = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    response = requests.post(
        url,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("errorCode"):
        raise RuntimeError(
            "cTrader token refresh failed: "
            f"{data.get('errorCode')} - "
            f"{data.get('description')}"
        )

    if "accessToken" not in data:
        raise RuntimeError(
            "cTrader token refresh response "
            "did not contain accessToken."
        )

    if "refreshToken" not in data:
        raise RuntimeError(
            "cTrader token refresh response "
            "did not contain refreshToken."
        )

    expires_in = int(
        data["expiresIn"]
    )

    return (
        data["accessToken"],
        data["refreshToken"],
        int(time.time()) + expires_in,
    )


def _update_github_secret(
    name: str,
    value: str,
) -> None:
    """
    Update one repository Actions secret using
    the repository public key.
    """
    if not GITHUB_PAT:
        raise RuntimeError(
            "GITHUB_PAT is required for automatic "
            "cTrader token rotation."
        )

    headers = {
        "Accept": (
            "application/vnd.github+json"
        ),
        "Authorization": (
            f"Bearer {GITHUB_PAT}"
        ),
        "X-GitHub-Api-Version": (
            "2022-11-28"
        ),
    }

    public_key_url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        "actions/secrets/public-key"
    )

    key_response = requests.get(
        public_key_url,
        headers=headers,
        timeout=30,
    )

    key_response.raise_for_status()

    key_data = key_response.json()

    repo_public_key = public.PublicKey(
        base64.b64decode(
            key_data["key"]
        ),
        encoding.RawEncoder(),
    )

    encrypted_value = (
        public.SealedBox(
            repo_public_key
        ).encrypt(
            value.encode("utf-8")
        )
    )

    secret_url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/"
        f"{GITHUB_REPO}/"
        f"actions/secrets/{name}"
    )

    payload = {
        "encrypted_value": (
            base64.b64encode(
                encrypted_value
            ).decode("utf-8")
        ),
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
    """
    Refresh the cTrader token when required and
    update the GitHub repository secrets.
    """
    global ACCESS_TOKEN
    global REFRESH_TOKEN
    global TOKEN_EXPIRES_AT

    if not _token_needs_refresh():
        return

    print(
        "cTrader access token needs refresh; "
        "requesting a new token..."
    )

    (
        new_access,
        new_refresh,
        new_expires_at,
    ) = _refresh_access_token()

    _update_github_secret(
        "CTRADER_ACCESS_TOKEN",
        new_access,
    )

    _update_github_secret(
        "CTRADER_REFRESH_TOKEN",
        new_refresh,
    )

    _update_github_secret(
        "CTRADER_TOKEN_EXPIRES_AT",
        str(new_expires_at),
    )

    ACCESS_TOKEN = new_access
    REFRESH_TOKEN = new_refresh
    TOKEN_EXPIRES_AT = (
        new_expires_at
    )

    print(
        "cTrader token refreshed successfully; "
        "GitHub secrets updated."
    )


# ============================================================
# RESPONSE HANDLING
# ============================================================

def _response_or_error(
    message,
    request_name: str,
):
    """
    Extract the underlying protobuf response and
    surface cTrader API errors clearly.
    """
    response = Protobuf.extract(
        message
    )

    error_code = getattr(
        response,
        "errorCode",
        None,
    )

    if error_code:
        description = getattr(
            response,
            "description",
            "",
        )

        raise RuntimeError(
            f"{request_name} rejected by cTrader: "
            f"{error_code} - {description}"
        )

    return response


# ============================================================
# TREND-BAR CONVERSION
# ============================================================

def _completed_candles(
    trendbars,
    digits: int,
    tf_minutes: int,
):
    """
    Convert cTrader trendbars into the dictionary
    format used by the existing VSA engine.
    """
    candles: list[
        dict[str, Any]
    ] = []

    for bar in trendbars:
        low = int(bar.low)

        open_raw = (
            low + int(bar.deltaOpen)
        )

        close_raw = (
            low + int(bar.deltaClose)
        )

        high_raw = (
            low + int(bar.deltaHigh)
        )

        timestamp = (
            int(
                bar.utcTimestampInMinutes
            )
            * 60
        )

        candles.append(
            {
                "time": (
                    datetime.fromtimestamp(
                        timestamp,
                        tz=timezone.utc,
                    ).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                ),
                "open": round(
                    open_raw / 100000.0,
                    digits,
                ),
                "high": round(
                    high_raw / 100000.0,
                    digits,
                ),
                "low": round(
                    low / 100000.0,
                    digits,
                ),
                "close": round(
                    close_raw / 100000.0,
                    digits,
                ),
                "volume": int(
                    bar.volume
                ),
            }
        )

    candles.sort(
        key=lambda row: row["time"]
    )

    # Remove the currently-forming candle.
    if candles:
        latest_dt = (
            datetime.fromisoformat(
                candles[-1]["time"].replace(
                    "Z",
                    "+00:00",
                )
            )
        )

        latest_epoch = int(
            latest_dt.timestamp()
        )

        interval = (
            tf_minutes * 60
        )

        current_bucket = (
            int(time.time())
            // interval
        ) * interval

        if (
            latest_epoch
            >= current_bucket
        ):
            candles.pop()

    return candles


# ============================================================
# COMPLETE cTRADER DATA PIPELINE
# ============================================================

def _fetch_all_timeframes():
    """
    One cTrader TCP session:

    ApplicationAuth
        ->
    GetAccountListByAccessToken
        ->
    AccountAuth
        ->
    SymbolList
        ->
    SymbolById
        ->
    Trendbars
    """
    host = (
        EndPoints.PROTOBUF_LIVE_HOST
        if ENVIRONMENT == "live"
        else EndPoints.PROTOBUF_DEMO_HOST
    )

    client = Client(
        host,
        EndPoints.PROTOBUF_PORT,
        TcpProtocol,
    )

    result_box: dict[
        str,
        Any,
    ] = {}

    errors: list[str] = []

    pending = set(
        TF_MINUTES.keys()
    )

    symbol_info: dict[
        str,
        Any,
    ] = {}

    # --------------------------------------------------------
    # ERROR / STOP HELPERS
    # --------------------------------------------------------

    def stop_with_error(
        message: str,
    ):
        errors.append(
            message
        )

        if reactor.running:
            reactor.stop()

    # --------------------------------------------------------
    # UNIVERSAL SEND WRAPPER
    # --------------------------------------------------------

    def send(
        request,
        callback,
        request_name: str,
    ):
        deferred = client.send(
            request
        )

        def handle_response(
            message,
        ):
            try:
                response = (
                    _response_or_error(
                        message,
                        request_name,
                    )
                )

                return callback(
                    response
                )

            except Exception as exc:
                stop_with_error(
                    str(exc)
                )

                return None

        def handle_failure(
            failure,
        ):
            stop_with_error(
                f"{request_name} transport failure: "
                f"{failure}"
            )

            return None

        deferred.addCallback(
            handle_response
        )

        deferred.addErrback(
            handle_failure
        )

        return deferred

    # --------------------------------------------------------
    # FINISH CHECK
    # --------------------------------------------------------

    def finish_if_done():
        if (
            not pending
            and reactor.running
        ):
            result_box["value"] = {
                tf: result_box[tf]
                for tf in TF_MINUTES
            }

            reactor.stop()

    # --------------------------------------------------------
    # TREND-BAR RESPONSE
    # --------------------------------------------------------

    def after_trendbars(
        tf: str,
        response,
    ):
        trendbars = getattr(
            response,
            "trendbar",
            None,
        )

        if not trendbars:
            raise RuntimeError(
                f"No trendbars returned for "
                f"{tf} / {SYMBOL_NAME} "
                f"(symbolId="
                f"{symbol_info['symbol_id']})."
            )

        candles = _completed_candles(
            trendbars,
            symbol_info[
                "digits"
            ],
            TF_MINUTES[tf],
        )

        if len(candles) < 20:
            raise RuntimeError(
                f"Only {len(candles)} completed "
                f"bars returned for {tf}; "
                "at least 20 are required "
                "by the VSA rules."
            )

        result_box[tf] = candles

        print(
            f"{tf}: received "
            f"{len(candles)} completed bars; "
            f"latest={candles[-1]['time']}"
        )

        pending.discard(
            tf
        )

        finish_if_done()

    # --------------------------------------------------------
    # TREND-BAR REQUESTS
    # --------------------------------------------------------

    def request_trendbars():
    """
    Request completed trendbars for every configured timeframe.

    cTrader requires both fromTimestamp and toTimestamp
    in ProtoOAGetTrendbarsReq.
    """
    now_ms = int(
        time.time() * 1000
    )

    for tf, tf_minutes in TF_MINUTES.items():
        request = (
            ProtoOAGetTrendbarsReq()
        )

        request.ctidTraderAccountId = (
            ACCOUNT_ID
        )

        request.symbolId = (
            symbol_info["symbol_id"]
        )

        request.period = (
            ProtoOATrendbarPeriod.Value(
                tf
            )
        )

        request.count = 60

        history_minutes = (
            (request.count + 5)
            * tf_minutes
        )

        request.fromTimestamp = (
            now_ms
            - (
                history_minutes
                * 60
                * 1000
            )
        )

        request.toTimestamp = now_ms

        send(
            request,
            lambda response, tf=tf:
                after_trendbars(
                    tf,
                    response,
                ),
            f"ProtoOAGetTrendbarsReq[{tf}]",
        )

    def after_symbol_details(
        response,
    ):
        symbols = getattr(
            response,
            "symbol",
            None,
        )

        if not symbols:
            raise RuntimeError(
                "cTrader returned no symbol "
                "details for symbolId="
                f"{symbol_info['symbol_id']}."
            )

        symbol = symbols[0]

        symbol_info["digits"] = int(
            symbol.digits
        )

        # IMPORTANT:
        # ProtoOASymbol returned by
        # ProtoOASymbolByIdReq does not
        # expose symbolName.
        print(
            f"Symbol details received for "
            f"{SYMBOL_NAME}; "
            f"digits="
            f"{symbol_info['digits']}"
        )

        request_trendbars()

    def request_symbol_details(
        symbol_id: int,
    ):
        request = (
            ProtoOASymbolByIdReq()
        )

        request.ctidTraderAccountId = (
            ACCOUNT_ID
        )

        request.symbolId.append(
            int(symbol_id)
        )

        send(
            request,
            after_symbol_details,
            "ProtoOASymbolByIdReq",
        )

    # --------------------------------------------------------
    # SYMBOL LIST
    # --------------------------------------------------------

    def after_symbols(
        response,
    ):
        symbols = getattr(
            response,
            "symbol",
            None,
        )

        if not symbols:
            raise RuntimeError(
                "cTrader returned an empty "
                "symbol list."
            )

        wanted = (
            SYMBOL_NAME
            .upper()
            .replace(
                "/",
                "",
            )
        )

        matches = []

        for symbol in symbols:
            symbol_name = (
                symbol.symbolName
                .upper()
                .replace(
                    "/",
                    "",
                )
            )

            if (
                symbol_name
                == wanted
            ):
                matches.append(
                    symbol
                )

        # Fallback to symbols containing XAUUSD.
        if not matches:
            for symbol in symbols:
                symbol_name = (
                    symbol.symbolName
                    .upper()
                    .replace(
                        "/",
                        "",
                    )
                )

                if (
                    "XAUUSD"
                    in symbol_name
                ):
                    matches.append(
                        symbol
                    )

        if not matches:
            names = [
                symbol.symbolName
                for symbol in symbols[:50]
            ]

            raise RuntimeError(
                f"{SYMBOL_NAME} not found on "
                "Pepperstone cTrader. "
                f"First available symbols: "
                f"{names}"
            )

        selected = matches[0]

        symbol_info[
            "symbol_id"
        ] = int(
            selected.symbolId
        )

        print(
            f"Using cTrader symbol: "
            f"{selected.symbolName} "
            f"(symbolId="
            f"{symbol_info['symbol_id']})"
        )

        request_symbol_details(
            symbol_info[
                "symbol_id"
            ]
        )

    # --------------------------------------------------------
    # ACCOUNT AUTH
    # --------------------------------------------------------

    def after_account_auth(
        response,
    ):
        account_id = getattr(
            response,
            "ctidTraderAccountId",
            ACCOUNT_ID,
        )

        print(
            "cTrader account authorized: "
            f"{account_id}"
        )

        request = (
            ProtoOASymbolsListReq()
        )

        request.ctidTraderAccountId = (
            ACCOUNT_ID
        )

        request.includeArchivedSymbols = (
            False
        )

        send(
            request,
            after_symbols,
            "ProtoOASymbolsListReq",
        )

    # --------------------------------------------------------
    # ACCOUNT LIST
    # --------------------------------------------------------

    def after_account_list(
        response,
    ):
        account_items = getattr(
            response,
            "ctidTraderAccount",
            None,
        )

        if not account_items:
            raise RuntimeError(
                "cTrader returned no accounts "
                "for this access token."
            )

        account_ids = [
            int(
                item.ctidTraderAccountId
            )
            for item in account_items
        ]

        print(
            "Accounts available to this "
            f"token: {account_ids}"
        )

        if ACCOUNT_ID not in account_ids:
            raise RuntimeError(
                f"Account ID {ACCOUNT_ID} "
                "is not present in the token's "
                f"authorized account list: "
                f"{account_ids}"
            )

        request = (
            ProtoOAAccountAuthReq()
        )

        request.ctidTraderAccountId = (
            ACCOUNT_ID
        )

        request.accessToken = (
            ACCESS_TOKEN
        )

        send(
            request,
            after_account_auth,
            "ProtoOAAccountAuthReq",
        )

    # --------------------------------------------------------
    # APPLICATION AUTH
    # --------------------------------------------------------

    def after_app_auth(
        _response,
    ):
        request = (
            ProtoOAGetAccountListByAccessTokenReq()
        )

        request.accessToken = (
            ACCESS_TOKEN
        )

        send(
            request,
            after_account_list,
            (
                "ProtoOAGetAccountListBy"
                "AccessTokenReq"
            ),
        )

    # --------------------------------------------------------
    # CONNECTION
    # --------------------------------------------------------

    def connected(
        _client,
    ):
        print(
            "Connected to cTrader Open API."
        )

        request = (
            ProtoOAApplicationAuthReq()
        )

        request.clientId = (
            CLIENT_ID
        )

        request.clientSecret = (
            CLIENT_SECRET
        )

        send(
            request,
            after_app_auth,
            "ProtoOAApplicationAuthReq",
        )

    def disconnected(
        _client,
        reason,
    ):
        if (
            not result_box
            and not errors
        ):
            errors.append(
                f"cTrader disconnected: "
                f"{reason}"
            )

        if reactor.running:
            reactor.stop()

    client.setConnectedCallback(
        connected
    )

    client.setDisconnectedCallback(
        disconnected
    )

    # --------------------------------------------------------
    # START cTRADER
    # --------------------------------------------------------

    client.startService()

    reactor.callLater(
        60,
        lambda: stop_with_error(
            "cTrader request timed out "
            "after 60 seconds."
        ),
    )

    reactor.run()

    # --------------------------------------------------------
    # FINAL VALIDATION
    # --------------------------------------------------------

    if errors:
        raise RuntimeError(
            errors[0]
        )

    if "value" not in result_box:
        raise RuntimeError(
            "cTrader returned no market-data "
            "result."
        )

    return result_box["value"]


# ============================================================
# PUBLIC API
# ============================================================

def get_candles(
    granularity,
    count=60,
):
    """
    Return the newest completed candles for
    the requested timeframe.
    """
    global _ALL_CANDLES

    if granularity not in TF_MINUTES:
        raise ValueError(
            f"Unsupported granularity: "
            f"{granularity}"
        )

    if _ALL_CANDLES is None:
        _maybe_refresh_token()

        _ALL_CANDLES = (
            _fetch_all_timeframes()
        )

    return _ALL_CANDLES[
        granularity
    ][-count:]

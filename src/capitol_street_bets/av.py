"""Alpha Vantage client with a budget, backoff, and plan detection.

The transport is injectable so tests never touch the network. The API key is
sent as a query parameter and is not included in exceptions or logs.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from capitol_street_bets.config import Settings
from capitol_street_bets.db import (
    connect,
    get_meta,
    log_request,
    recent_request_times,
    requests_today,
    set_meta,
)

MINUTE_RE = re.compile(r"(\d+)\s+calls per minute", re.I)
DAY_RE = re.compile(r"(\d+)\s+calls per day", re.I)
PREMIUM_RE = re.compile(r"premium", re.I)

Transport = Callable[[dict[str, str]], dict]


class AVError(RuntimeError):
    pass


class RateLimitError(AVError):
    def __init__(self, message: str, per_minute: int | None, per_day: int | None):
        super().__init__(message)
        self.per_minute = per_minute
        self.per_day = per_day


class DailyBudgetSpent(AVError):
    pass


@dataclass
class DetectedLimits:
    per_minute: int | None = None
    per_day: int | None = None
    premium_price_blocked: bool = False


def urllib_transport(base_url: str, timeout: float = 45.0) -> Transport:
    def _fetch(params: dict[str, str]) -> dict:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{base_url}?{query}",
            headers={"User-Agent": "capitol-street-bets/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise AVError(f"HTTP {exc.code} from Alpha Vantage") from exc
        except urllib.error.URLError as exc:
            raise AVError("network error talking to Alpha Vantage") from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AVError("Alpha Vantage returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise AVError("Alpha Vantage returned an unexpected payload")
        return payload

    return _fetch


def throttle_message(payload: dict) -> str | None:
    for key in ("Note", "Information", "Error Message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_limits(message: str) -> DetectedLimits:
    detected = DetectedLimits()
    minute = MINUTE_RE.search(message)
    day = DAY_RE.search(message)
    if minute:
        detected.per_minute = int(minute.group(1))
    if day:
        detected.per_day = int(day.group(1))
    if PREMIUM_RE.search(message) and "endpoint" in message.lower():
        detected.premium_price_blocked = True
    return detected


def is_throttle(payload: dict) -> bool:
    message = throttle_message(payload)
    if not message:
        return False
    # A premium-endpoint notice is a capability error, not a pace error,
    # unless it also states a call frequency.
    if parse_limits(message).per_minute or parse_limits(message).per_day:
        return True
    lowered = message.lower()
    return "frequency" in lowered or "rate limit" in lowered or "api call" in lowered


class AlphaVantageClient:
    def __init__(
        self,
        settings: Settings,
        conn,
        transport: Transport | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
        max_retries: int = 4,
    ):
        self.settings = settings
        self.conn = conn
        self.transport = transport or urllib_transport(settings.base_url)
        self.sleep = sleep or time.sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_retries = max_retries
        self.price_function = settings.price_function
        self.outputsize = settings.outputsize
        self._load_detected()

    def _load_detected(self) -> None:
        minute = get_meta(self.conn, "detected_per_minute")
        day = get_meta(self.conn, "detected_per_day")
        function_name = get_meta(self.conn, "price_function")
        outputsize = get_meta(self.conn, "outputsize")
        if minute:
            self.settings = _replace(self.settings, requests_per_minute=int(minute))
        if day:
            self.settings = _replace(self.settings, requests_per_day=int(day))
        if function_name:
            self.price_function = function_name
        if outputsize:
            self.outputsize = outputsize

    def _remember_limits(self, detected: DetectedLimits) -> None:
        if detected.per_minute:
            set_meta(self.conn, "detected_per_minute", str(detected.per_minute))
            self.settings = _replace(self.settings, requests_per_minute=detected.per_minute)
        if detected.per_day:
            set_meta(self.conn, "detected_per_day", str(detected.per_day))
            self.settings = _replace(self.settings, requests_per_day=detected.per_day)
        self.conn.commit()

    def _acquire(self, function_name: str) -> None:
        day = self.clock().date()
        daily = self.settings.requests_per_day
        if daily > 0 and requests_today(self.conn, day) >= daily:
            raise DailyBudgetSpent(
                f"daily budget of {daily} Alpha Vantage requests is spent"
            )
        per_minute = self.settings.requests_per_minute
        while True:
            now = self.clock()
            cutoff = now - timedelta(seconds=60)
            recent = []
            for stamp in recent_request_times(self.conn):
                parsed = datetime.fromisoformat(stamp)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed >= cutoff:
                    recent.append(parsed)
            if len(recent) < per_minute:
                break
            oldest = min(recent)
            wait = (oldest + timedelta(seconds=60) - now).total_seconds()
            self.sleep(max(0.05, wait))
        log_request(self.conn, day, function_name, "sent")
        self.conn.commit()

    def call(self, function_name: str, **params: str) -> dict:
        if not self.settings.api_key:
            raise AVError("ALPHAVANTAGE_API_KEY is not set")
        query = {"function": function_name, "apikey": self.settings.api_key, **params}
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._acquire(function_name)
            # The transport receives the key. Callers and exceptions do not.
            payload = self.transport(dict(query))
            message = throttle_message(payload)
            if message and is_throttle(payload):
                detected = parse_limits(message)
                self._remember_limits(detected)
                lowered = message.lower()
                # The minute note names both caps ("5 per minute and 25 per
                # day"); the daily one only names the day.
                if (detected.per_day and not detected.per_minute) or (
                    "per day" in lowered and "minute" not in lowered and "frequency" not in lowered
                ):
                    # Retrying a daily cap only burns local budget. Stop for today.
                    set_meta(self.conn, "av_last_limit_message", message[:300])
                    self.conn.commit()
                    raise DailyBudgetSpent("Alpha Vantage says the daily limit is reached: " + message[:200])
                last_error = RateLimitError(message, detected.per_minute, detected.per_day)
                self.sleep(min(8.0, 0.5 * (2**attempt)))
                continue
            if message and parse_limits(message).premium_price_blocked and function_name.endswith("ADJUSTED"):
                set_meta(self.conn, "price_function", "TIME_SERIES_DAILY")
                self.price_function = "TIME_SERIES_DAILY"
                self.conn.commit()
                raise AVError("adjusted daily prices are not on this plan; switched to TIME_SERIES_DAILY")
            if message and "Error Message" in payload and "Time Series" not in payload:
                raise AVError("Alpha Vantage rejected the request")
            return payload
        assert last_error is not None
        raise last_error

    def politician_metadata(self) -> dict:
        return self.call("POLITICIAN_METADATA")

    def congress_trades(self, bioguide_id: str) -> dict:
        return self.call("CONGRESS_TRADES", bioguide_id=bioguide_id)

    def congress_trades_by_symbol(self, symbol: str) -> dict:
        return self.call("CONGRESS_TRADES", symbol=symbol)

    def daily_prices(self, symbol: str) -> dict:
        return self.call(
            self.price_function,
            symbol=symbol,
            outputsize=self.outputsize,
        )


def _replace(settings: Settings, **changes) -> Settings:
    data = settings.__dict__.copy()
    data.update(changes)
    return Settings(**data)


def parse_daily_series(payload: dict) -> dict[str, tuple[float, float | None]]:
    """Map a daily time-series payload to date -> (close, adjusted_or_none)."""
    series = None
    for key, value in payload.items():
        if key.lower().startswith("time series") and isinstance(value, dict):
            series = value
            break
    if series is None:
        raise AVError("price payload had no time series")
    bars: dict[str, tuple[float, float | None]] = {}
    for day, row in series.items():
        if not isinstance(row, dict):
            continue
        close = _field(row, "close", adjusted=False)
        adjusted = _field(row, "adjusted close", adjusted=True)
        if close is None and adjusted is None:
            continue
        bars[str(day)[:10]] = (close if close is not None else adjusted or 0.0, adjusted)
    return bars


def _field(row: dict, label: str, adjusted: bool) -> float | None:
    for key, value in row.items():
        lowered = key.lower().strip()
        if adjusted:
            if not lowered.endswith("adjusted close"):
                continue
        else:
            if not lowered.endswith("close") or "adjusted" in lowered:
                continue
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def last_expected_session(day: date) -> date:
    """Latest weekday on or before day. Holidays are not special-cased."""
    cursor = day
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor

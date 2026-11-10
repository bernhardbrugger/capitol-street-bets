"""Daily closes from Massive (formerly Polygon.io).

The free Basic plan has no daily cap, five calls a minute and two years of
end-of-day history. That covers prices completely, so the whole Alpha
Vantage budget can go to member filings.

Two calls do all the work:

* ``/v2/aggs/ticker/{T}/range/1/day/{from}/{to}``: two years for a ticker we
  have never priced. One call per new ticker.
* ``/v2/aggs/grouped/locale/us/market/stocks/{date}``: every US ticker for one
  session. One call per day keeps every known ticker current.

The key travels in the Authorization header only. It never appears in a URL,
an error message, the cache or the site.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE_URL = "https://api.massive.com"
NEW_YORK = ZoneInfo("America/New_York")

Transport = Callable[[str, dict], tuple[int, dict]]


class MassiveError(RuntimeError):
    pass


class MassiveNotAuthorized(MassiveError):
    pass


def _default_transport(key: str, timeout: float = 30.0) -> Transport:
    def send(path: str, params: dict) -> tuple[int, dict]:
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {key}", "User-Agent": "capitol-street-bets"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                body = {}
            return exc.code, body
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MassiveError(f"network error: {type(exc).__name__}") from None

    return send


class MassiveClient:
    def __init__(
        self,
        key: str,
        per_minute: int = 5,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not key:
            raise MassiveError("MASSIVE_API_KEY is not set")
        self._transport = transport or _default_transport(key)
        self._sleep = sleep
        self._monotonic = monotonic
        self._gap = 60.0 / max(1, per_minute) + 0.25
        self._last = None
        self.calls = 0

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(4):
            if self._last is not None:
                wait = self._gap - (self._monotonic() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._monotonic()
            self.calls += 1
            status, body = self._transport(path, params)
            if status == 429:
                self._sleep(61.0)
                continue
            if status in (401, 403):
                raise MassiveNotAuthorized(str(body.get("message") or body.get("status") or status)[:200])
            if status >= 400:
                raise MassiveError(f"HTTP {status}: {str(body.get('message') or body.get('error') or '')[:200]}")
            return body
        raise MassiveError("rate limited four times in a row")

    def ticker_history(self, symbol: str, start: date, end: date) -> dict[str, float]:
        path = f"/v2/aggs/ticker/{urllib.parse.quote(symbol, safe='')}/range/1/day/{start.isoformat()}/{end.isoformat()}"
        body = self._get(path, {"adjusted": "true", "sort": "asc", "limit": 50000})
        return _closes(body.get("results") or [], symbol=None)

    def grouped(self, day: date) -> dict[str, float]:
        path = f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
        body = self._get(path, {"adjusted": "true"})
        out: dict[str, float] = {}
        for row in body.get("results") or []:
            symbol = row.get("T")
            close = row.get("c")
            if symbol and isinstance(close, (int, float)) and close > 0:
                out[str(symbol).upper()] = float(close)
        return out


def _session_day(ms: int | float) -> str:
    """Massive stamps daily bars at the session start in New York time."""
    moment = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(NEW_YORK)
    return moment.date().isoformat()


def _closes(results: list[dict], symbol: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in results:
        close = row.get("c")
        stamp = row.get("t")
        if isinstance(close, (int, float)) and close > 0 and isinstance(stamp, (int, float)):
            out[_session_day(stamp)] = float(close)
    return out


def massive_symbol(symbol: str) -> str:
    """Filings write share classes with a dot (BRK.B); Massive does too."""
    return symbol.strip().upper().replace("-", ".")


def sessions_between(start: date, end: date) -> list[date]:
    """Weekdays in (start, end]. Holidays come back empty and are skipped."""
    days = []
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days

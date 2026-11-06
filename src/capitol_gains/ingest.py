"""Incremental, resumable ingestion.

A finite daily budget rotates through the roster and the ticker list. A plan
with no daily cap (AV_REQUESTS_PER_DAY=0) walks everything that is stale,
throttled to the per-minute limit. Price history that already covers the
latest weekday is not requested again. A member payload whose hash did not
change is not rewritten.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from capitol_gains.av import (
    AVError,
    AlphaVantageClient,
    DailyBudgetSpent,
    RateLimitError,
    last_expected_session,
    parse_daily_series,
)
from capitol_gains.config import Settings
from capitol_gains.db import (
    distinct_trade_symbols,
    get_meta,
    iter_trades,
    last_bar,
    list_politicians,
    load_price_book_rows,
    mark_price_sync,
    member_hash,
    replace_member_trades,
    set_meta,
    store_prices,
    upsert_politicians,
)
from capitol_gains.league import (
    assemble_league,
    is_current,
    load_history,
    politician_from_api,
    write_site,
)
from capitol_gains.models import Trade
from capitol_gains.prices import PriceBook
from capitol_gains.returns import classify_asset, trade_from_api


def vendor_symbol(symbol: str) -> str:
    """Alpha Vantage uses a dash for share classes (BRK-B). Filings often use a dot."""
    return symbol.upper().replace(".", "-")


def trade_key(bioguide_id: str, payload: dict) -> str:
    parts = [
        bioguide_id,
        payload.get("transaction_date"),
        payload.get("filed_date"),
        payload.get("symbol"),
        payload.get("transaction_type"),
        payload.get("amount_min"),
        payload.get("amount_max"),
        payload.get("owner_code"),
        payload.get("asset_name"),
        payload.get("notification_date"),
    ]
    blob = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def content_hash(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def budget_plan(
    room: int,
    metadata_due: bool,
    members_waiting: int,
    prices_waiting: int,
    price_share: float,
    unlimited: bool,
) -> dict[str, int]:
    """How many calls this run may spend on each job, given the room that is left."""
    if room <= 0:
        return {"metadata": 0, "members": 0, "prices": 0}
    metadata = 1 if metadata_due else 0
    if metadata > room:
        metadata = room
    rest = room - metadata
    if unlimited:
        prices = min(prices_waiting, rest)
        members = min(members_waiting, rest - prices)
        # Members first when the plan can finish both: prices are what mark
        # the book to market, so give them the room they need and spend the
        # leftover on members. Callers pass prices_waiting from the stale set.
        if prices_waiting + members_waiting <= rest:
            return {"metadata": metadata, "members": members_waiting, "prices": prices_waiting}
        # Still finite per run. Keep the configured share so a huge ticker
        # list cannot starve the roster, and the other way around.
    if not members_waiting:
        price_slots = min(prices_waiting, rest)
    else:
        # Keep a member slot whenever the room is tight so a small daily
        # budget cannot spend its last call on a price and stall the roster.
        price_slots = min(prices_waiting, int(round(rest * price_share)))
        if rest - price_slots < 1:
            price_slots = 0 if rest == 1 else rest - 1
    member_slots = min(members_waiting, rest - price_slots)
    return {"metadata": metadata, "members": member_slots, "prices": price_slots}


def _metadata_due(conn, today: date, refresh_days: int) -> bool:
    raw = get_meta(conn, "metadata_fetched_on")
    if not raw:
        return True
    try:
        fetched = date.fromisoformat(raw)
    except ValueError:
        return True
    return (today - fetched).days >= refresh_days


def _member_queue(conn, today: date, limit: int) -> list[str]:
    if limit <= 0:
        return []
    rows = conn.execute(
        """
        SELECT p.bioguide_id
        FROM politicians p
        LEFT JOIN member_sync s ON s.bioguide_id = p.bioguide_id
        WHERE s.last_fetched_at IS NULL OR substr(s.last_fetched_at, 1, 10) != ?
        ORDER BY p.is_current DESC,
                 s.last_fetched_at IS NOT NULL,
                 s.last_fetched_at ASC,
                 p.bioguide_id ASC
        LIMIT ?
        """,
        (today.isoformat(), limit),
    ).fetchall()
    return [row["bioguide_id"] for row in rows]


def _price_queue(conn, today: date, limit: int) -> list[str]:
    if limit <= 0:
        return []
    expected = last_expected_session(today).isoformat()
    symbols = ["SPY", *distinct_trade_symbols(conn)]
    seen = set()
    ordered = []
    for symbol in symbols:
        if symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    stale = []
    for symbol in ordered:
        last = last_bar(conn, symbol)
        if last is not None and last >= expected:
            continue
        stale.append(symbol)
    # SPY first, then the rest of the stale list, which is already stable.
    stale.sort(key=lambda symbol: (symbol != "SPY", last_bar(conn, symbol) or "", symbol))
    return stale[:limit]


def _waiting_counts(conn, today: date) -> tuple[int, int]:
    members = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM politicians p
        LEFT JOIN member_sync s ON s.bioguide_id = p.bioguide_id
        WHERE s.last_fetched_at IS NULL OR substr(s.last_fetched_at, 1, 10) != ?
        """,
        (today.isoformat(),),
    ).fetchone()["n"]
    expected = last_expected_session(today).isoformat()
    symbols = set(distinct_trade_symbols(conn))
    symbols.add("SPY")
    prices = 0
    for symbol in symbols:
        last = last_bar(conn, symbol)
        if last is None or last < expected:
            prices += 1
    return int(members), prices


def ingest(settings: Settings, conn, client: AlphaVantageClient, today: date | None = None) -> dict:
    """Fetch what the budget allows. Returns a small report. Never raises on a spent budget."""
    today = today or client.clock().date()
    if settings.daily_unlimited:
        spent = 0
        room = settings.max_requests_per_run
    else:
        from capitol_gains.db import requests_today

        spent = requests_today(conn, today)
        room = max(0, settings.requests_per_day - spent)
    meta_due = _metadata_due(conn, today, settings.metadata_refresh_days)
    members_waiting, prices_waiting = _waiting_counts(conn, today)
    # Metadata has to land before we know the roster. On a first run the
    # member count is zero until that call returns, so reserve the slot and
    # recompute the split after.
    plan = budget_plan(
        room,
        meta_due,
        members_waiting,
        prices_waiting,
        settings.price_budget_share,
        settings.daily_unlimited,
    )
    report = {
        "metadata": False,
        "members": [],
        "prices": [],
        "skipped_unchanged_members": [],
        "stopped": None,
        "plan": plan,
        "detected_per_minute": settings.requests_per_minute,
        "detected_per_day": settings.requests_per_day,
    }
    try:
        if plan["metadata"]:
            _pull_metadata(client, conn, today)
            report["metadata"] = True
            members_waiting, prices_waiting = _waiting_counts(conn, today)
            # Room left after the metadata call.
            from capitol_gains.db import requests_today as _count

            used_now = _count(conn, today)
            if settings.daily_unlimited:
                room_left = max(0, settings.max_requests_per_run - used_now)
            else:
                room_left = max(0, settings.requests_per_day - used_now)
            plan = budget_plan(
                room_left,
                False,
                members_waiting,
                prices_waiting,
                settings.price_budget_share,
                settings.daily_unlimited,
            )
            report["plan_after_metadata"] = plan
        for bioguide_id in _member_queue(conn, today, plan["members"]):
            try:
                changed = _pull_member(client, conn, bioguide_id)
            except AVError as exc:
                if isinstance(exc, (RateLimitError, DailyBudgetSpent)):
                    raise
                report.setdefault("member_errors", []).append(
                    {"bioguide_id": bioguide_id, "error": _safe(str(exc))}
                )
                continue
            report["members"].append(bioguide_id)
            if not changed:
                report["skipped_unchanged_members"].append(bioguide_id)
        # Prices depend on tickers we just stored. Recompute the stale set,
        # still capped by the original price allotment. One bad symbol does
        # not cancel the rest of the run.
        price_limit = plan["prices"]
        for symbol in _price_queue(conn, today, price_limit):
            try:
                _pull_price(client, conn, symbol, today)
            except AVError as exc:
                if isinstance(exc, (RateLimitError, DailyBudgetSpent)):
                    raise
                report.setdefault("price_errors", []).append(
                    {"symbol": symbol, "error": _safe(str(exc))}
                )
                continue
            report["prices"].append(symbol)
    except DailyBudgetSpent as exc:
        report["stopped"] = str(exc)
    except RateLimitError as exc:
        report["stopped"] = "rate limit: " + _safe(str(exc))
    report["detected_per_minute"] = client.settings.requests_per_minute
    report["detected_per_day"] = client.settings.requests_per_day
    set_meta(conn, "last_ingest_report", json.dumps({k: v for k, v in report.items() if k != "plan"}))
    conn.commit()
    return report


def _safe(text: str) -> str:
    return text.replace("\n", " ")[:240]


def _pull_metadata(client: AlphaVantageClient, conn, today: date) -> None:
    payload = client.politician_metadata()
    rows = payload.get("politicians") or payload.get("data") or []
    if not isinstance(rows, list):
        raise AVError("politician metadata did not include a list")
    as_of = today
    cooked = []
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("bioguide_id"):
            continue
        person = politician_from_api(raw, as_of)
        cooked.append(
            {
                "bioguide_id": person.bioguide_id,
                "name": person.name,
                "chamber": person.chamber,
                "party": person.party,
                "state": person.state,
                "district": person.district,
                "is_current": is_current(raw.get("terms") or [], as_of),
                "terms": person.terms,
                "raw": raw,
            }
        )
    upsert_politicians(conn, cooked)
    set_meta(conn, "metadata_fetched_on", today.isoformat())
    conn.commit()


def _pull_member(client: AlphaVantageClient, conn, bioguide_id: str) -> bool:
    payload = client.congress_trades(bioguide_id)
    trades = payload.get("trades") or []
    if not isinstance(trades, list):
        raise AVError("congress trades did not include a list")
    digest = content_hash(trades)
    previous = member_hash(conn, bioguide_id)
    stamp = client.clock().replace(microsecond=0).isoformat()
    if previous == digest:
        conn.execute(
            """
            INSERT INTO member_sync (bioguide_id, last_fetched_at, content_hash, status)
            VALUES (?, ?, ?, 'unchanged')
            ON CONFLICT(bioguide_id) DO UPDATE SET
                last_fetched_at = excluded.last_fetched_at,
                status = 'unchanged'
            """,
            (bioguide_id, stamp, digest),
        )
        conn.commit()
        return False
    rows = []
    for raw in trades:
        if not isinstance(raw, dict):
            continue
        rows.append({"trade_id": trade_key(bioguide_id, raw), "payload": raw})
    replace_member_trades(conn, bioguide_id, rows, digest, fetched_at=stamp)
    conn.commit()
    return True


def _pull_price(client: AlphaVantageClient, conn, symbol: str, today: date) -> None:
    expected = last_expected_session(today).isoformat()
    if (last_bar(conn, symbol) or "") >= expected:
        return
    requested = vendor_symbol(symbol)
    try:
        payload = client.daily_prices(requested)
    except AVError as exc:
        if "TIME_SERIES_DAILY" not in str(exc):
            raise
        payload = client.daily_prices(requested)
    bars = parse_daily_series(payload)
    store_prices(conn, symbol, bars)
    latest = max(bars) if bars else last_bar(conn, symbol)
    mark_price_sync(conn, symbol, latest, client.price_function)
    conn.commit()


def compute_site(settings: Settings, conn, as_of: date | None = None) -> dict:
    """Score whatever is cached and write the static JSON."""
    as_of = as_of or datetime.now(timezone.utc).date()
    politicians = []
    current_ids = set()
    for row in list_politicians(conn):
        raw = json.loads(row["raw_json"])
        politicians.append(politician_from_api(raw, as_of))
        if row["is_current"]:
            current_ids.add(row["bioguide_id"])
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for bioguide_id, payload in iter_trades(conn):
        grouped[bioguide_id].append(trade_from_api(payload, bioguide_id))
    priced = load_price_book_rows(conn)
    series = {
        symbol: {date.fromisoformat(day): value for day, value in points.items()}
        for symbol, points in priced.items()
    }
    book = PriceBook(series)
    included = [
        person
        for person in politicians
        if person.bioguide_id in current_ids or grouped.get(person.bioguide_id)
    ]
    history = load_history(settings.site_data / "rank-history.json")
    price_mode = get_meta(conn, "price_function", settings.price_function) or settings.price_function
    notes = [
        "Position size is the midpoint of the disclosed range.",
        "Alpha compares each holding period with SPY over those same dates.",
    ]
    if price_mode == "TIME_SERIES_DAILY":
        notes.append(
            "Closes are raw TIME_SERIES_DAILY prints. Split-adjusted history needs a premium plan."
        )
    league, members, updated = assemble_league(
        included,
        grouped,
        book,
        as_of,
        history,
        min_trades=settings.min_trades,
        late_days=settings.late_days,
        sample=False,
        price_mode="adjusted" if "ADJUSTED" in price_mode else "unadjusted",
        notes=notes,
    )
    write_site(settings.site_data, league, members, updated)
    return {"members": len(included), "as_of": as_of.isoformat()}

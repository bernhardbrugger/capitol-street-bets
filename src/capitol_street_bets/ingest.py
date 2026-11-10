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

from capitol_street_bets.av import (
    AVError,
    AlphaVantageClient,
    DailyBudgetSpent,
    RateLimitError,
    last_expected_session,
    parse_daily_series,
)
from capitol_street_bets.config import Settings
from capitol_street_bets.db import (
    distinct_trade_symbols,
    get_meta,
    iter_trades,
    last_bar,
    list_politicians,
    load_price_book_rows,
    mark_price_sync,
    member_hash,
    replace_activity_hints,
    replace_member_trades,
    set_meta,
    store_prices,
    upsert_politicians,
)
from capitol_street_bets.league import (
    assemble_league,
    is_current,
    load_history,
    politician_from_api,
    write_site,
)
from capitol_street_bets.models import Trade
from capitol_street_bets.prices import PriceBook
from capitol_street_bets.returns import classify_asset, trade_from_api


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
        # Reserve the share even when no ticker is known yet: on a fresh cache
        # the trades (and so the tickers) only arrive during this run.
        price_slots = int(round(rest * price_share))
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


def _member_queue(conn, today: date, limit: int, settings: Settings | None = None) -> list[str]:
    """Who to fetch next.

    Never-fetched members that discovery saw trading come first, busiest first.
    Then the rest of the never-fetched roster. Members already fetched are
    refreshed every few days if they have trades, and only every couple of
    months if their last pull came back empty.
    """
    if limit <= 0:
        return []
    active_days = settings.active_refresh_days if settings else 3
    inactive_days = settings.inactive_refresh_days if settings else 60
    rows = conn.execute(
        """
        SELECT p.bioguide_id, p.is_current, s.last_fetched_at,
               (SELECT COUNT(*) FROM trades t WHERE t.bioguide_id = p.bioguide_id) AS stored,
               (SELECT COALESCE(SUM(h.trades), 0) FROM activity_hint h WHERE h.bioguide_id = p.bioguide_id) AS hinted
        FROM politicians p
        LEFT JOIN member_sync s ON s.bioguide_id = p.bioguide_id
        """
    ).fetchall()
    picks = []
    for row in rows:
        fetched = row["last_fetched_at"]
        if fetched:
            age = (today - date.fromisoformat(fetched[:10])).days
            if age <= 0:
                continue
            if row["stored"] == 0 and age < inactive_days:
                continue
            if row["stored"] > 0 and age < active_days:
                continue
        key = (
            fetched is not None,          # never fetched first
            -int(row["hinted"] or 0) if fetched is None else 0,
            not row["is_current"],        # seated before former members
            fetched or "",                # stalest first
            row["bioguide_id"],
        )
        picks.append((key, row["bioguide_id"]))
    picks.sort()
    return [bid for _, bid in picks[:limit]]


def _equity_symbol_counts(conn) -> dict[str, int]:
    """Tickers in at least one scoreable equity trade. Options, funds, bonds
    and mystery tickers would spend a call and never score."""
    counts: dict[str, int] = defaultdict(int)
    for bioguide_id, payload in iter_trades(conn):
        try:
            trade = trade_from_api(payload, bioguide_id)
        except Exception:
            continue
        if classify_asset(trade) == "equity" and trade.symbol:
            counts[trade.symbol.strip().upper()] += 1
    return counts


def _price_queue(conn, today: date, limit: int) -> list[str]:
    if limit <= 0:
        return []
    expected = last_expected_session(today).isoformat()
    counts = _equity_symbol_counts(conn)
    symbols = ["SPY", *sorted(counts)]
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
    # SPY first, then never-priced tickers by how many trades they unlock,
    # then the stalest of the rest. On a small daily budget this ranks members
    # as early as possible.
    stale.sort(
        key=lambda symbol: (
            symbol != "SPY",
            last_bar(conn, symbol) is not None,
            -counts.get(symbol, 0),
            last_bar(conn, symbol) or "",
            symbol,
        )
    )
    return stale[:limit]


def _waiting_counts(conn, today: date) -> tuple[int, int]:
    members = len(_member_queue(conn, today, 10**5))
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
        from capitol_street_bets.db import requests_today

        spent = requests_today(conn, today)
        room = max(0, settings.requests_per_day - spent)
    meta_due = _metadata_due(conn, today, settings.metadata_refresh_days)
    members_waiting, prices_waiting = _waiting_counts(conn, today)
    massive = bool(settings.massive_api_key)
    price_share = 0.0 if massive else settings.price_budget_share
    if massive:
        prices_waiting = 0
    # Metadata has to land before we know the roster. On a first run the
    # member count is zero until that call returns, so reserve the slot and
    # recompute the split after.
    plan = budget_plan(
        room,
        meta_due,
        members_waiting,
        prices_waiting,
        price_share,
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
            if massive:
                prices_waiting = 0
            # Room left after the metadata call.
            from capitol_street_bets.db import requests_today as _count

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
                price_share,
                settings.daily_unlimited,
            )
            report["plan_after_metadata"] = plan
        member_slots = plan["members"]
        due = _discovery_due(conn, settings, today)
        if due and member_slots > 1:
            # Up to four discovery calls a run, always leaving member slots.
            take = min(len(due), 4, max(1, member_slots // 3))
            for symbol in due[:take]:
                try:
                    _pull_discovery(client, conn, symbol, today)
                    report.setdefault("discovery", []).append(symbol)
                except AVError as exc:
                    if isinstance(exc, (RateLimitError, DailyBudgetSpent)):
                        raise
                    report.setdefault("discovery_errors", []).append({"symbol": symbol, "error": _safe(str(exc))})
                member_slots -= 1
        for bioguide_id in _member_queue(conn, today, member_slots, settings):
            try:
                changed = _pull_member(client, conn, bioguide_id)
            except AVError as exc:
                if isinstance(exc, (RateLimitError, DailyBudgetSpent)):
                    raise
                report.setdefault("member_errors", []).append(
                    {"bioguide_id": bioguide_id, "error": _safe(str(exc))}
                )
                continue
            except Exception as exc:  # one odd payload must not cost the whole run
                conn.rollback()
                report.setdefault("member_errors", []).append(
                    {"bioguide_id": bioguide_id, "error": _safe(f"{type(exc).__name__}: {exc}")}
                )
                continue
            report["members"].append(bioguide_id)
            if not changed:
                report["skipped_unchanged_members"].append(bioguide_id)
        # Prices depend on tickers we just stored. Recompute the stale set,
        # still capped by the original price allotment. One bad symbol does
        # not cancel the rest of the run.
        # Whatever the member loop left over also goes to prices.
        from capitol_street_bets.db import requests_today as _spent

        used = _spent(conn, today)
        cap = settings.max_requests_per_run if settings.daily_unlimited else settings.requests_per_day
        price_limit = max(plan["prices"], cap - used if not settings.daily_unlimited else plan["prices"])
        for symbol in ([] if massive else _price_queue(conn, today, price_limit)):
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


def _discovery_due(conn, settings: Settings, today: date) -> list[str]:
    due = []
    for symbol in settings.discovery_symbols:
        last = get_meta(conn, f"discovery:{symbol}")
        if last and (today - date.fromisoformat(last)).days < settings.discovery_refresh_days:
            continue
        due.append(symbol)
    return due


def _pull_discovery(client: AlphaVantageClient, conn, symbol: str, today: date) -> None:
    """Count recent trades per member in one symbol's disclosures.

    Only a hint for queue order. Member trades still come from the member's own
    pull, so nobody's record is built from a partial, ticker-filtered view.
    """
    payload = client.congress_trades_by_symbol(symbol)
    trades = payload.get("trades") or []
    if not isinstance(trades, list):
        raise AVError("congress trades did not include a list")
    cutoff = (today - timedelta(days=730)).isoformat()
    counts: dict[str, tuple[int, str | None]] = {}
    for raw in trades:
        if not isinstance(raw, dict):
            continue
        bid = str(raw.get("bioguide_id") or "").strip()
        when = str(raw.get("transaction_date") or "")[:10]
        if not bid or (when and when < cutoff):
            continue
        n, last = counts.get(bid, (0, None))
        counts[bid] = (n + 1, max(last or "", when) or None)
    replace_activity_hints(conn, symbol, counts)
    set_meta(conn, f"discovery:{symbol}", today.isoformat())
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
    seen: dict[str, int] = {}
    for raw in trades:
        if not isinstance(raw, dict):
            continue
        key = trade_key(bioguide_id, raw)
        # Two buys of the same ticker, same day, same range and owner are two
        # real transactions with identical disclosed fields. Keep both.
        count = seen.get(key, 0)
        seen[key] = count + 1
        rows.append({"trade_id": key if count == 0 else f"{key}-{count}", "payload": raw})
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
    if get_meta(conn, "price_source") == "massive":
        price_mode = "MASSIVE_ADJUSTED"
    notes = [
        "Position size is the midpoint of the disclosed range.",
        "Alpha compares each holding period with SPY over those same dates.",
    ]
    if price_mode == "MASSIVE_ADJUSTED":
        notes.append("Daily closes from Massive (formerly Polygon.io), split-adjusted.")
    elif price_mode == "TIME_SERIES_DAILY":
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
    synced = conn.execute(
        "SELECT COUNT(*) FROM member_sync s JOIN politicians p USING (bioguide_id) WHERE p.is_current = 1"
    ).fetchone()[0]
    tickers = _equity_symbol_counts(conn)
    priced = sum(1 for symbol in tickers if last_bar(conn, symbol) is not None)
    league["coverage"] = {
        "members_loaded": int(synced),
        "members_seated": len(current_ids),
        "members_trading": sum(1 for bid in current_ids if grouped.get(bid)),
        "tickers_priced": priced,
        "tickers_total": len(tickers),
    }
    write_site(settings.site_data, league, members, updated)
    return {"members": len(included), "as_of": as_of.isoformat()}


def ingest_massive_prices(settings: Settings, conn, client, today: date | None = None) -> dict:
    """Backfill two years for tickers we have never priced, then catch every
    priced ticker up with one grouped call per missing session."""
    from capitol_street_bets.massive import MassiveError, MassiveNotAuthorized, massive_symbol, sessions_between

    today = today or datetime.now(timezone.utc).date()
    # The run starts before the US open: the newest finished session is the
    # previous weekday.
    target = last_expected_session(today - timedelta(days=1))
    budget = settings.massive_max_calls_per_run
    report: dict = {"backfilled": [], "empty": [], "sessions": [], "errors": [], "stopped": None}
    counts = _equity_symbol_counts(conn)
    symbols = ["SPY", *sorted((s for s in counts if s != "SPY"), key=lambda s: (-counts[s], s))]
    start = target - timedelta(days=settings.massive_history_days)
    try:
        for symbol in symbols:
            if client.calls >= budget:
                report["stopped"] = f"per-run cap of {budget} calls"
                break
            if last_bar(conn, symbol):
                continue
            tried = get_meta(conn, f"massive_empty:{symbol}")
            if tried and (today - date.fromisoformat(tried)).days < 30:
                continue
            try:
                closes = client.ticker_history(massive_symbol(symbol), start, target)
            except MassiveNotAuthorized:
                raise
            except MassiveError as exc:
                report["errors"].append({"symbol": symbol, "error": _safe(str(exc))})
                continue
            if not closes:
                set_meta(conn, f"massive_empty:{symbol}", today.isoformat())
                report["empty"].append(symbol)
                conn.commit()
                continue
            store_prices(conn, symbol, {day: (close, close) for day, close in closes.items()})
            mark_price_sync(conn, symbol, max(closes), "MASSIVE")
            conn.commit()
            report["backfilled"].append(symbol)

        known = {symbol: last_bar(conn, symbol) for symbol in symbols}
        known = {symbol: last for symbol, last in known.items() if last}
        floor = (target - timedelta(days=45)).isoformat()
        behind = [last for last in known.values() if floor <= last < target.isoformat()]
        if behind and not report["stopped"]:
            for day in sessions_between(date.fromisoformat(min(behind)), target):
                if client.calls >= budget:
                    report["stopped"] = f"per-run cap of {budget} calls"
                    break
                try:
                    closes = client.grouped(day)
                except MassiveNotAuthorized:
                    raise
                except MassiveError as exc:
                    report["errors"].append({"session": day.isoformat(), "error": _safe(str(exc))})
                    continue
                if not closes:
                    continue  # market holiday
                iso = day.isoformat()
                for symbol, last in known.items():
                    close = closes.get(massive_symbol(symbol))
                    if close is None or last >= iso:
                        continue
                    store_prices(conn, symbol, {iso: (close, close)})
                    mark_price_sync(conn, symbol, iso, "MASSIVE")
                    known[symbol] = iso
                conn.commit()
                report["sessions"].append(iso)
    except MassiveNotAuthorized as exc:
        report["stopped"] = "not authorized: " + _safe(str(exc))
    if not str(report["stopped"] or "").startswith("not authorized"):
        set_meta(conn, "price_source", "massive")
    report["calls"] = client.calls
    set_meta(conn, "last_massive_report", json.dumps(report))
    conn.commit()
    return report

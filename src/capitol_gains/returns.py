"""Holding-period returns from disclosed ranges.

See METHODOLOGY.md. Amounts are midpoints. Buys open lots, sales close them
FIFO, leftovers are marked to market. SPY is measured on the same dates.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from capitol_gains.models import (
    HoldingSlice,
    MeasuredLot,
    MemberStats,
    Trade,
    WindowPerformance,
    parse_amount,
    parse_date,
)
from capitol_gains.prices import PriceBook
from capitol_gains.sectors import is_tech

EQUITY_CODES = {"st", "stock", "etf", "etn"}
OPTION_CODES = {"op", "opt", "option", "stock option"}
NON_STOCK_WORDS = (
    "bond",
    "note",
    "treasury",
    "municipal",
    "crypto",
    "bitcoin",
    "real estate",
    "option",
)
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
SOURCE_KEYS = (
    "source_url",
    "sourceUrl",
    "disclosure_url",
    "filing_url",
    "ptr_url",
    "link",
    "url",
)


def midpoint(amount_min: float | None, amount_max: float | None) -> tuple[float | None, str]:
    """Return (dollars, how). Open-ended buckets use the only side we have."""
    if amount_min is None and amount_max is None:
        return None, "missing"
    if amount_min is not None and amount_max is not None:
        return (amount_min + amount_max) / 2.0, "midpoint"
    if amount_min is not None:
        return amount_min, "open_ended_floor"
    return amount_max, "open_ended_cap"


def _clean_ticker(value: object) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "N/A", "NA", "NONE", "NULL", "--", "-"}:
        return ""
    return text


def _first_url(raw: dict) -> str | None:
    for key in SOURCE_KEYS:
        value = raw.get(key)
        if not value:
            continue
        text = str(value).strip()
        if text.lower().startswith(("http://", "https://")):
            return text
    return None


def trade_from_api(raw: dict, bioguide_fallback: str = "") -> Trade:
    """Map one Alpha Vantage CONGRESS_TRADES row. Unknown keys stay in raw."""
    symbol = _clean_ticker(raw.get("symbol") or raw.get("ticker") or raw.get("ticker_reported"))
    return Trade(
        bioguide_id=str(raw.get("bioguide_id") or bioguide_fallback or "").strip(),
        symbol=symbol,
        transaction_type=str(raw.get("transaction_type") or raw.get("type") or "").strip(),
        transaction_date=parse_date(raw.get("transaction_date")),
        filed_date=parse_date(raw.get("filed_date") or raw.get("filing_date")),
        notification_date=parse_date(raw.get("notification_date")),
        amount_min=parse_amount(raw.get("amount_min") if "amount_min" in raw else raw.get("amount_low")),
        amount_max=parse_amount(raw.get("amount_max") if "amount_max" in raw else raw.get("amount_high")),
        asset_name=str(raw.get("asset_name") or raw.get("asset") or "").strip(),
        asset_type_code=(None if raw.get("asset_type_code") in (None, "") else str(raw.get("asset_type_code"))),
        owner_code=(None if raw.get("owner_code") in (None, "") else str(raw.get("owner_code"))),
        source_url=_first_url(raw),
        chamber=(None if raw.get("chamber") in (None, "") else str(raw.get("chamber"))),
        raw=raw,
    )


def side_of(transaction_type: str) -> str | None:
    text = transaction_type.strip().lower()
    if text.startswith("sale") or text.startswith("sell") or "sold" in text:
        return "sell"
    if text.startswith("buy") or "purchase" in text or "bought" in text:
        return "buy"
    return None


def classify_asset(trade: Trade) -> str:
    """Return equity, option, non_stock, or unknown."""
    code = (trade.asset_type_code or "").strip().lower()
    name = (trade.asset_name or "").lower()
    if code in OPTION_CODES or "option" in name:
        return "option"
    if any(word in name for word in NON_STOCK_WORDS if word != "option"):
        return "non_stock"
    ticker_ok = bool(TICKER_RE.fullmatch(trade.symbol or ""))
    if not ticker_ok:
        return "unknown"
    if code in EQUITY_CODES:
        return "equity"
    if code in {"", "none"}:
        if "stock" in name or "etf" in name or "[st]" in name:
            return "equity"
        return "non_stock"
    return "non_stock"


def filing_lag_days(trade: Trade) -> int | None:
    disclosed = trade.disclosure_date
    if trade.transaction_date is None or disclosed is None:
        return None
    return (disclosed - trade.transaction_date).days


def is_late(trade: Trade, late_days: int = 45) -> bool:
    lag = filing_lag_days(trade)
    return lag is not None and lag > late_days


def _price(book: PriceBook, symbol: str, day: date) -> float | None:
    return book.on_or_before(symbol, day)


class _Lot:
    def __init__(self, symbol: str, shares: float, cost: float, entry_date: date, entry_price: float, disclosure: date | None):
        self.symbol = symbol
        self.shares = shares
        self.cost = cost
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.disclosure_date = disclosure
        self.original_shares = shares


def build_slices(trades: list[Trade], book: PriceBook) -> tuple[list[HoldingSlice], dict[str, int]]:
    """FIFO lots per ticker. Counts explain everything that did not become a lot."""
    counts = {
        "options": 0,
        "non_stock": 0,
        "unknown": 0,
        "other": 0,
        "unmatched_sells": 0,
        "missing_amount": 0,
        "missing_price": 0,
    }
    by_symbol: dict[str, list[Trade]] = {}
    for trade in trades:
        kind = classify_asset(trade)
        if kind == "option":
            counts["options"] += 1
            continue
        if kind == "non_stock":
            counts["non_stock"] += 1
            continue
        if kind == "unknown":
            counts["unknown"] += 1
            continue
        action = side_of(trade.transaction_type)
        if action is None:
            counts["other"] += 1
            continue
        if trade.transaction_date is None:
            counts["other"] += 1
            continue
        by_symbol.setdefault(trade.symbol, []).append(trade)

    slices: list[HoldingSlice] = []
    for symbol, group in by_symbol.items():
        ordered = sorted(
            group,
            key=lambda t: (t.transaction_date or date.min, 0 if side_of(t.transaction_type) == "buy" else 1),
        )
        open_lots: list[_Lot] = []
        for trade in ordered:
            action = side_of(trade.transaction_type)
            px = _price(book, symbol, trade.transaction_date) if trade.transaction_date else None
            dollars, _how = midpoint(trade.amount_min, trade.amount_max)
            if dollars is None or dollars <= 0 or px is None or px <= 0 or trade.transaction_date is None:
                if dollars is None or dollars <= 0:
                    counts["missing_amount"] += 1
                else:
                    counts["missing_price"] += 1
                continue
            shares = dollars / px
            if action == "buy":
                open_lots.append(
                    _Lot(symbol, shares, dollars, trade.transaction_date, px, trade.disclosure_date)
                )
                continue
            remaining = shares
            while remaining > 1e-9 and open_lots:
                lot = open_lots[0]
                take = min(lot.shares, remaining)
                cost_slice = lot.cost * (take / lot.shares)
                lot.cost -= cost_slice
                lot.shares -= take
                remaining -= take
                slices.append(
                    HoldingSlice(
                        symbol=symbol,
                        shares=take,
                        cost=cost_slice,
                        entry_date=lot.entry_date,
                        entry_price=lot.entry_price,
                        exit_date=trade.transaction_date,
                        exit_price=px,
                        disclosure_date=lot.disclosure_date,
                    )
                )
                if lot.shares <= 1e-9:
                    open_lots.pop(0)
            if remaining > 1e-6:
                counts["unmatched_sells"] += 1
        for lot in open_lots:
            slices.append(
                HoldingSlice(
                    symbol=symbol,
                    shares=lot.shares,
                    cost=lot.cost,
                    entry_date=lot.entry_date,
                    entry_price=lot.entry_price,
                    exit_date=None,
                    exit_price=None,
                    disclosure_date=lot.disclosure_date,
                )
            )
    return slices, counts


def _measure_slice(
    sl: HoldingSlice,
    book: PriceBook,
    window_start: date,
    window_end: date,
    mode: str,
) -> MeasuredLot | str:
    """Return a lot, or a short reason string."""
    if mode == "copycat":
        if sl.disclosure_date is None:
            return "uncopyable"
        if sl.exit_date is not None and sl.exit_date < sl.disclosure_date:
            return "uncopyable"
        entry = sl.disclosure_date
        entry_px = _price(book, sl.symbol, entry)
        if entry_px is None or entry_px <= 0:
            return "missing_price"
        shares = sl.cost / entry_px
    else:
        entry = sl.entry_date
        entry_px = sl.entry_price
        shares = sl.shares
    if entry > window_end:
        return "outside"
    exit_day = sl.exit_date or window_end
    if exit_day < window_start:
        return "outside"
    t0 = max(entry, window_start)
    t1 = min(exit_day, window_end)
    if t1 <= t0:
        return "no_span"
    p0 = _price(book, sl.symbol, t0)
    p1 = _price(book, sl.symbol, t1)
    s0 = _price(book, "SPY", t0)
    s1 = _price(book, "SPY", t1)
    if p0 is None or p1 is None or s0 is None or s1 is None or p0 <= 0 or s0 <= 0:
        return "missing_price"
    weight = shares * p0
    if weight <= 0:
        return "missing_price"
    pnl = shares * (p1 - p0)
    benchmark_pnl = weight * ((s1 / s0) - 1.0)
    return MeasuredLot(
        symbol=sl.symbol,
        pnl=pnl,
        weight=weight,
        benchmark_pnl=benchmark_pnl,
        entry_date=t0,
        exit_date=t1,
        hold_days=(t1 - sl.entry_date).days if mode == "their" else (t1 - entry).days,
    )


def measure(
    slices: list[HoldingSlice],
    book: PriceBook,
    window_start: date,
    window_end: date,
    mode: str,
) -> WindowPerformance:
    lots: list[MeasuredLot] = []
    uncopyable = 0
    missing = 0
    for sl in slices:
        result = _measure_slice(sl, book, window_start, window_end, mode)
        if isinstance(result, MeasuredLot):
            lots.append(result)
        elif result == "uncopyable":
            uncopyable += 1
        elif result == "missing_price":
            missing += 1
    weight = sum(lot.weight for lot in lots)
    if weight <= 0:
        return WindowPerformance(None, None, None, 0.0, lots, uncopyable, missing)
    pnl = sum(lot.pnl for lot in lots)
    bench = sum(lot.benchmark_pnl for lot in lots)
    member = pnl / weight
    benchmark = bench / weight
    return WindowPerformance(member, benchmark, member - benchmark, weight, lots, uncopyable, missing)


def window_bounds(name: str, as_of: date) -> tuple[date, date]:
    if name == "30d":
        return as_of - timedelta(days=30), as_of
    if name == "ytd":
        return date(as_of.year, 1, 1), as_of
    if name == "12m":
        return as_of - timedelta(days=365), as_of
    if name == "all":
        return date(1990, 1, 1), as_of
    raise KeyError(name)


WINDOWS = ("30d", "ytd", "12m", "all")


def _in_window(day: date | None, start: date, end: date) -> bool:
    return day is not None and start <= day <= end


def score_member(
    trades: list[Trade],
    book: PriceBook,
    window_name: str,
    as_of: date,
    late_days: int = 45,
    with_curve: bool = False,
) -> MemberStats:
    start, end = window_bounds(window_name, as_of)
    slices, counts = build_slices(trades, book)
    their = measure(slices, book, start, end, "their")
    copycat = measure(slices, book, start, end, "copycat")

    trade_count = 0
    dollars = 0.0
    tech_dollars = 0.0
    sized: list[float] = []
    lags: list[int] = []
    late = 0
    filings = 0
    on_time = 0
    for trade in trades:
        if classify_asset(trade) != "equity" or side_of(trade.transaction_type) is None:
            continue
        if trade.transaction_date is None:
            continue
        px = _price(book, trade.symbol, trade.transaction_date)
        dollars_mid, _how = midpoint(trade.amount_min, trade.amount_max)
        priced = px is not None and dollars_mid is not None and dollars_mid > 0
        if _in_window(trade.transaction_date, start, end) and priced:
            trade_count += 1
            assert dollars_mid is not None
            dollars += dollars_mid
            sized.append(dollars_mid)
            if is_tech(trade.symbol):
                tech_dollars += dollars_mid
        disclosed = trade.disclosure_date
        if _in_window(disclosed, start, end):
            lag = filing_lag_days(trade)
            filings += 1
            if lag is not None and lag >= 0:
                lags.append(lag)
                if lag > late_days:
                    late += 1
                else:
                    on_time += 1

    hold_values = [lot.hold_days for lot in their.lots]
    realized = measure_closed(slices, book, start, end)

    stats = MemberStats(
        their_return=their.member_return,
        their_alpha=their.alpha,
        their_benchmark=their.benchmark_return,
        copycat_return=copycat.member_return,
        copycat_alpha=copycat.alpha,
        trade_count=trade_count,
        excluded_options=counts["options"],
        excluded_non_stock=counts["non_stock"],
        excluded_unknown=counts["unknown"] + counts["missing_price"],
        excluded_other=counts["other"] + counts["missing_amount"],
        unmatched_sells=counts["unmatched_sells"],
        uncopyable=copycat.uncopyable,
        avg_hold_days=(sum(hold_values) / len(hold_values)) if hold_values else None,
        avg_filing_lag=(sum(lags) / len(lags)) if lags else None,
        late_filings=late,
        filings=filings,
        on_time_filings=on_time,
        tech_share=(tech_dollars / dollars) if dollars > 0 else None,
        top_two_share=_top_two_share(sized),
        realized_return=realized,
        weight=their.weight,
        curve=equity_curve(slices, book, start, end) if with_curve else [],
    )
    return stats


def measure_closed(slices: list[HoldingSlice], book: PriceBook, start: date, end: date) -> float | None:
    """Capital-weighted close-to-close return of lots sold inside the window."""
    pnl = 0.0
    weight = 0.0
    for sl in slices:
        if sl.exit_date is None or sl.exit_date < start or sl.exit_date > end:
            continue
        result = _measure_slice(sl, book, sl.entry_date, sl.exit_date, "their")
        if not isinstance(result, MeasuredLot):
            continue
        # Re-measure the whole life of the closed lot, then keep it only when
        # the sale itself lands in the window. _measure_slice from entry to
        # exit ignores the scoreboard window, which is what "timing" means.
        pnl += result.pnl
        weight += result.weight
    if weight <= 0:
        return None
    return pnl / weight


def _top_two_share(sized: list[float]) -> float | None:
    if not sized:
        return None
    ordered = sorted(sized, reverse=True)
    total = sum(ordered)
    if total <= 0:
        return None
    return sum(ordered[:2]) / total


def equity_curve(
    slices: list[HoldingSlice],
    book: PriceBook,
    window_start: date,
    window_end: date,
) -> list[dict]:
    """Chain their-return periods. Both lines start at 100."""
    dates = _curve_dates(slices, book, window_start, window_end)
    if len(dates) < 2:
        return []
    member_idx = 100.0
    spy_idx = 100.0
    points = [{"date": dates[0].isoformat(), "member": 100.0, "spy": 100.0}]
    for prev, curr in zip(dates, dates[1:]):
        perf = measure(slices, book, prev, curr, "their")
        if perf.member_return is not None and perf.benchmark_return is not None and perf.weight > 0:
            member_idx *= 1.0 + perf.member_return
            spy_idx *= 1.0 + perf.benchmark_return
        points.append(
            {
                "date": curr.isoformat(),
                "member": round(member_idx, 4),
                "spy": round(spy_idx, 4),
            }
        )
    return points


def _curve_dates(
    slices: list[HoldingSlice],
    book: PriceBook,
    window_start: date,
    window_end: date,
) -> list[date]:
    if "SPY" not in book.series:
        return []
    spy_dates = [d for d in book._dates.get("SPY", []) if window_start <= d <= window_end]
    if not spy_dates:
        return []
    entries = [sl.entry_date for sl in slices if sl.entry_date <= window_end]
    if not entries:
        return []
    first = max(window_start, min(entries))
    grid = [d for d in spy_dates if d >= first]
    if not grid:
        return []
    # Keep endpoints and every 5th session so member JSON stays small.
    picked = [grid[0]]
    for i, day in enumerate(grid):
        if i % 5 == 0:
            picked.append(day)
    if grid[-1] != picked[-1]:
        picked.append(grid[-1])
    # Unique, stable.
    out: list[date] = []
    for day in picked:
        if not out or out[-1] != day:
            out.append(day)
    return out


def realized_return_for(slices: list[HoldingSlice], book: PriceBook, start: date, end: date) -> float | None:
    return measure_closed(slices, book, start, end)

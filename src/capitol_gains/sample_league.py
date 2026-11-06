"""A fictional league so the site is usable before the first API pull.

Members, trades, and prices are made up. Nothing here is a real disclosure.
The same scoring code that runs on Alpha Vantage data builds the JSON.
"""

from __future__ import annotations

from datetime import date, timedelta

from capitol_gains.league import assemble_league, empty_history_from_snapshots, write_site
from capitol_gains.models import Politician, Trade
from capitol_gains.prices import PriceBook

AS_OF = date(2026, 11, 6)
START = date(2025, 6, 2)


def business_days(start: date, end: date) -> list[date]:
    days = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _series(days: list[date], fn) -> dict[date, float]:
    total = len(days)
    return {day: round(float(fn(index, total)), 4) for index, day in enumerate(days)}


def price_book(days: list[date]) -> PriceBook:
    def spy(i, n):
        return 500 * (1.00035**i)

    def boom(i, n):
        # Tracks the market, then gaps up on the final session.
        base = 50 * (1.0004**i)
        if i == n - 1:
            return base * 1.16
        return base

    def spike(i, n):
        # Leads the league until the final session, then gives it back.
        climbed = 42 * (1.0035**i)
        if i == n - 1:
            return climbed * 0.48
        return climbed

    def lift(i, n):
        # Three modest steps on the last three sessions. Sized so the holder
        # passes about one neighbor per day instead of leaping the pack.
        base = 80 * (1.00045**i)
        if i == n - 3:
            return base * 1.0018
        if i == n - 2:
            return base * 1.0018 * 1.0028
        if i == n - 1:
            return base * 1.0018 * 1.0028 * 1.0096
        return base

    def msft(i, n):
        return 410 * (1.00055**i)

    def aapl(i, n):
        return 190 * (1.00045**i)

    def nvda(i, n):
        return 120 * (1.0011**i)

    def fade(i, n):
        return 140 * (0.9988**i)

    def jnj(i, n):
        return 160 * (0.9997**i)

    def xom(i, n):
        return 108 * (1.00015**i)

    return PriceBook(
        {
            "SPY": _series(days, spy),
            "BOOM": _series(days, boom),
            "SPIKE": _series(days, spike),
            "MSFT": _series(days, msft),
            "AAPL": _series(days, aapl),
            "NVDA": _series(days, nvda),
            "FADE": _series(days, fade),
            "JNJ": _series(days, jnj),
            "XOM": _series(days, xom),
            "LIFT": _series(days, lift),
        }
    )


def _person(bioguide, name, chamber, party, state, district, start, end=None) -> Politician:
    term = {
        "chamber": chamber.lower(),
        "state": state,
        "district": district,
        "start_date": start.isoformat(),
        "end_date": None if end is None else end.isoformat(),
    }
    return Politician(
        bioguide_id=bioguide,
        name=name,
        chamber="Senate" if chamber.lower().startswith("sen") else "House",
        party=party,
        state=state,
        district=district,
        terms=[term],
        years_in_service=round(((end or AS_OF) - start).days / 365.25, 1),
    )


def _trade(bioguide, symbol, side, when: date, lo, hi, lag_days: int) -> Trade:
    return Trade(
        bioguide_id=bioguide,
        symbol=symbol,
        transaction_type="BUY" if side == "buy" else "SELL",
        transaction_date=when,
        filed_date=when + timedelta(days=lag_days),
        notification_date=when + timedelta(days=min(lag_days, 3)),
        amount_min=float(lo),
        amount_max=float(hi),
        asset_name=f"{symbol} common stock [ST]",
        asset_type_code="ST",
        owner_code="SELF",
        source_url=None,
        chamber=None,
    )


def _option(bioguide, when: date) -> Trade:
    return Trade(
        bioguide_id=bioguide,
        symbol="SPY",
        transaction_type="BUY",
        transaction_date=when,
        filed_date=when + timedelta(days=6),
        notification_date=when,
        amount_min=1001,
        amount_max=15000,
        asset_name="SPY Jan 2027 500 call option",
        asset_type_code="OP",
        owner_code="SELF",
        source_url=None,
    )


def roster() -> list[Politician]:
    return [
        _person("CG0001", "Jordan Hale", "house", "D", "CA", "12", date(2019, 1, 3)),
        _person("CG0002", "Casey Nguyen", "senate", "R", "WA", None, date(2017, 1, 3)),
        _person("CG0003", "Riley Okonkwo", "house", "D", "NY", "7", date(2021, 1, 3)),
        _person("CG0004", "Morgan Ellis", "senate", "I", "ME", None, date(2015, 1, 6)),
        _person("CG0005", "Avery Shah", "house", "R", "TX", "24", date(2023, 1, 3)),
        _person("CG0006", "Quinn Alvarez", "house", "D", "NM", "1", date(2013, 1, 3)),
        _person("CG0007", "Parker Singh", "senate", "R", "OH", None, date(2019, 1, 3)),
        _person("CG0008", "Drew Coleman", "house", "R", "FL", "3", date(2025, 1, 3)),
        _person("CG0009", "Skyler Brooks", "senate", "D", "HI", None, date(2021, 1, 3)),
        _person("CG0010", "Reese Dalton", "house", "D", "WA", "1", date(2018, 1, 3)),
        _person("CG0011", "Jamie Ortiz", "house", "R", "AZ", "2", date(2020, 1, 3)),
        _person("CG0012", "Taylor Idris", "senate", "D", "CO", None, date(2025, 1, 3)),
        _person("CG0013", "Rowan Blake", "house", "R", "MI", "8", date(2011, 1, 3)),
    ]


def trades_for(days: list[date]) -> dict[str, list[Trade]]:
    by_id: dict[str, list[Trade]] = {person.bioguide_id: [] for person in roster()}

    def add(bioguide, symbol, side, when, lo, hi, lag):
        by_id[bioguide].append(_trade(bioguide, symbol, side, when, lo, hi, lag))

    # Jordan: three similar BOOM buys. The final-session gap is what moves rank.
    add("CG0001", "BOOM", "buy", date(2026, 10, 9), 15001, 50000, 6)
    add("CG0001", "BOOM", "buy", date(2026, 10, 20), 15001, 50000, 5)
    add("CG0001", "BOOM", "buy", date(2026, 11, 2), 15001, 50000, 3)
    by_id["CG0001"].append(_option("CG0001", date(2026, 10, 15)))

    # Casey: LIFT, three buys, filed on time. The last three sessions step up.
    add("CG0002", "LIFT", "buy", date(2026, 10, 8), 50001, 100000, 6)
    add("CG0002", "LIFT", "buy", date(2026, 10, 16), 50001, 100000, 5)
    add("CG0002", "LIFT", "buy", date(2026, 10, 28), 50001, 100000, 4)

    # Riley: three SPIKE buys inside the month, still open into the gap down.
    add("CG0003", "SPIKE", "buy", date(2026, 10, 8), 100001, 250000, 9)
    add("CG0003", "SPIKE", "buy", date(2026, 10, 16), 100001, 250000, 8)
    add("CG0003", "SPIKE", "buy", date(2026, 10, 27), 250001, 500000, 6)

    # Morgan: SPY in, SPY out, SPY again. Alpha should sit on the index.
    add("CG0004", "SPY", "buy", date(2026, 10, 8), 15001, 50000, 4)
    add("CG0004", "SPY", "buy", date(2026, 10, 16), 15001, 50000, 4)
    add("CG0004", "SPY", "sell", date(2026, 10, 28), 1001, 15000, 5)
    add("CG0004", "SPY", "buy", date(2026, 10, 29), 15001, 50000, 3)

    # Avery: one large NVDA ticket and two small ones.
    add("CG0005", "NVDA", "buy", date(2026, 10, 13), 1000001, 5000000, 11)
    add("CG0005", "XOM", "buy", date(2026, 10, 14), 1001, 15000, 9)
    add("CG0005", "XOM", "buy", date(2026, 10, 22), 1001, 15000, 7)

    # Quinn: three old AAPL lots, still open. Long hold, no recent trades.
    add("CG0006", "AAPL", "buy", date(2025, 6, 3), 15001, 50000, 12)
    add("CG0006", "AAPL", "buy", date(2025, 7, 15), 15001, 50000, 10)
    add("CG0006", "AAPL", "buy", date(2025, 9, 2), 15001, 50000, 8)

    # Parker: buy NVDA and sell it three trading-ish days later, over and over.
    round_trips = [
        (date(2026, 9, 8), date(2026, 9, 11)),
        (date(2026, 9, 22), date(2026, 9, 25)),
        (date(2026, 10, 8), date(2026, 10, 13)),
        (date(2026, 10, 20), date(2026, 10, 23)),
        (date(2026, 11, 2), date(2026, 11, 5)),
    ]
    for opened, closed in round_trips:
        add("CG0007", "NVDA", "buy", opened, 15001, 50000, 4)
        add("CG0007", "NVDA", "sell", closed, 15001, 50000, 3)

    # Drew: trades from August, filings that land in late October. Lag is 80 days.
    for when in (date(2026, 8, 3), date(2026, 8, 12), date(2026, 8, 20)):
        add("CG0008", "JNJ", "buy", when, 15001, 50000, 80)

    # Skyler: on-time XOM trades inside the month.
    add("CG0009", "XOM", "buy", date(2026, 10, 9), 15001, 50000, 4)
    add("CG0009", "XOM", "buy", date(2026, 10, 19), 1001, 15000, 5)
    add("CG0009", "XOM", "sell", date(2026, 11, 3), 1001, 15000, 2)

    # Reese: technology names only.
    add("CG0010", "AAPL", "buy", date(2026, 10, 8), 15001, 50000, 6)
    add("CG0010", "MSFT", "buy", date(2026, 10, 15), 15001, 50000, 6)
    add("CG0010", "NVDA", "buy", date(2026, 10, 27), 50001, 100000, 5)

    # Jamie: buy FADE, sell it lower. Repeated.
    fades = [
        (date(2026, 8, 4), date(2026, 9, 2)),
        (date(2026, 9, 15), date(2026, 10, 13)),
        (date(2026, 10, 16), date(2026, 11, 4)),
    ]
    for opened, closed in fades:
        add("CG0011", "FADE", "buy", opened, 50001, 100000, 9)
        add("CG0011", "FADE", "sell", closed, 50001, 100000, 6)

    # Taylor: a single recent buy. Benched.
    add("CG0012", "AAPL", "buy", date(2026, 10, 21), 1001, 15000, 7)

    # Rowan: a lagging JNJ book with enough trades to be ranked.
    add("CG0013", "JNJ", "buy", date(2026, 10, 8), 15001, 50000, 10)
    add("CG0013", "JNJ", "buy", date(2026, 10, 19), 15001, 50000, 8)
    add("CG0013", "JNJ", "buy", date(2026, 10, 27), 15001, 50000, 6)

    # A bond that should be excluded, so the member page has something to count.
    by_id["CG0013"].append(
        Trade(
            bioguide_id="CG0013",
            symbol="",
            transaction_type="BUY",
            transaction_date=date(2026, 10, 2),
            filed_date=date(2026, 10, 12),
            notification_date=date(2026, 10, 2),
            amount_min=15001,
            amount_max=50000,
            asset_name="U.S. Treasury Note 4.25% 2030",
            asset_type_code=None,
            owner_code="SELF",
            source_url=None,
        )
    )
    return by_id


def build_sample(as_of: date = AS_OF):
    days = business_days(START, as_of)
    book = price_book(days)
    people = roster()
    grouped = trades_for(days)
    history_days = days[-6:-1]
    history = empty_history_from_snapshots(people, grouped, book, history_days, min_trades=3, late_days=45)
    notes = [
        "Sample league: fictional members and simulated prices, not live disclosures.",
        "Run `python -m capitol_gains run` with ALPHAVANTAGE_API_KEY set to replace this board.",
        "Position size is the midpoint of the disclosed range.",
    ]
    return assemble_league(
        people,
        grouped,
        book,
        as_of,
        history,
        min_trades=3,
        late_days=45,
        sample=True,
        price_mode="sample",
        notes=notes,
    )


def write_sample(site_data) -> dict:
    league, members, history = build_sample()
    write_site(site_data, league, members, history)
    return league


def summarize(league: dict) -> str:
    lines = []
    window = league["windows"]["30d"]
    lines.append(f"as_of {window['as_of']} beat {window['beat_market']}/{window['field_size']}")
    for row in window["ranked"]:
        flags = []
        if row["on_fire"]:
            flags.append(f"fire:{row['streak']}")
        if row["elevator"]:
            flags.append("elevator")
        if row["took_first"]:
            flags.append("first")
        badge_ids = ",".join(badge["id"] for badge in row["badges"])
        lines.append(
            f"#{row['rank']:2} {row['rank_change']!s:>4} {row['name']:<18} "
            f"a={row['alpha']} r={row['return']} {badge_ids} {' '.join(flags)}"
        )
    lines.append("-- benched --")
    for row in window["benched"]:
        badge_ids = ",".join(badge["id"] for badge in row["badges"])
        lines.append(
            f"    {row['name']:<18} trades={row['trades']} hold={row['avg_hold_days']} "
            f"lag={row['avg_filing_lag']} {badge_ids}"
        )
    return "\n".join(lines)

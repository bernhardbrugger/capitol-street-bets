"""Turn politicians, trades, and prices into the JSON the site reads."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from capitol_street_bets.badges import BADGE_COPY, assign_badges
from capitol_street_bets.commentary import build_tape
from capitol_street_bets.models import BoardRow, Politician, Trade
from capitol_street_bets.prices import PriceBook
from capitol_street_bets.ranks import ELEVATOR_DROP, apply_history, is_elevator, order_rows
from capitol_street_bets.returns import (
    WINDOWS,
    classify_asset,
    filing_lag_days,
    is_late,
    midpoint,
    score_member,
    side_of,
    window_bounds,
)

DISCLAIMER = (
    "For entertainment. Based on public disclosures via Alpha Vantage. "
    "Amounts are estimated from disclosed ranges. Not financial advice."
)
ATTRIBUTION = "Data: Alpha Vantage"

HOUSE_PORTAL = "https://disclosures-clerk.house.gov/FinancialDisclosure"
SENATE_PORTAL = "https://efdsearch.senate.gov/search/"


def years_in_service(terms: list[dict], as_of: date) -> float:
    intervals: list[list[date]] = []
    for term in terms or []:
        start = _parse(term.get("start_date"))
        if start is None:
            continue
        end = _parse(term.get("end_date")) or as_of
        end = min(end, as_of)
        if end < start:
            continue
        intervals.append([start, end])
    intervals.sort()
    merged: list[list[date]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    days = sum((end - start).days for start, end in merged)
    return round(days / 365.25, 1)


def _parse(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def initials(name: str) -> str:
    parts = [part for part in name.replace(".", " ").split() if part and part.lower() not in {"hon"}]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def chamber_label(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text.startswith("sen"):
        return "Senate"
    if text.startswith("hou"):
        return "House"
    return value or ""


def disclosure_portal(chamber: str | None) -> str:
    if chamber_label(chamber) == "Senate":
        return SENATE_PORTAL
    return HOUSE_PORTAL


def politician_from_api(raw: dict, as_of: date) -> Politician:
    terms = list(raw.get("terms") or [])
    return Politician(
        bioguide_id=str(raw.get("bioguide_id") or "").strip(),
        name=str(raw.get("display_name") or raw.get("politician_canonical") or raw.get("name") or "").strip(),
        chamber=chamber_label(raw.get("chamber")),
        party=str(raw.get("party") or "").strip(),
        state=str(raw.get("state") or "").strip(),
        district=None if raw.get("district") in (None, "") else str(raw.get("district")),
        terms=terms,
        years_in_service=years_in_service(terms, as_of),
    )


def is_current(raw_terms: list[dict], as_of: date) -> bool:
    for term in raw_terms or []:
        start = _parse(term.get("start_date"))
        end = _parse(term.get("end_date"))
        if start and start <= as_of and (end is None or end >= as_of):
            return True
    return False


def _row_payload(row: BoardRow) -> dict:
    stats = row.stats
    return {
        "bioguide_id": row.bioguide_id,
        "name": row.name,
        "initials": row.initials,
        "chamber": row.chamber,
        "party": row.party,
        "state": row.state,
        "district": row.district,
        "years_in_service": row.years_in_service,
        "rank": row.rank,
        "previous_rank": row.previous_rank,
        "rank_change": row.rank_change,
        "streak": row.streak,
        "on_fire": row.on_fire,
        "took_first": row.took_first,
        "elevator": is_elevator(row.rank_change),
        "elevator_drop": ELEVATOR_DROP,
        "benched": row.benched,
        "return": _round(stats.their_return),
        "alpha": _round(stats.their_alpha),
        "benchmark": _round(stats.their_benchmark),
        "copycat_return": _round(stats.copycat_return),
        "copycat_alpha": _round(stats.copycat_alpha),
        "trades": stats.trade_count,
        "avg_hold_days": None if stats.avg_hold_days is None else round(stats.avg_hold_days, 1),
        "avg_filing_lag": None if stats.avg_filing_lag is None else round(stats.avg_filing_lag, 1),
        "late_filings": stats.late_filings,
        "filings": stats.filings,
        "excluded_options": stats.excluded_options,
        "excluded_non_stock": stats.excluded_non_stock,
        "excluded_unknown": stats.excluded_unknown,
        "unmatched_sells": stats.unmatched_sells,
        "uncopyable": stats.uncopyable,
        "badges": [
            {"id": badge, "name": BADGE_COPY[badge]["name"], "blurb": BADGE_COPY[badge]["blurb"]}
            for badge in row.badges
            if badge in BADGE_COPY
        ],
        "top_ticker": None,
    }


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)


def build_window(
    politicians: list[Politician],
    trades_by_member: dict[str, list[Trade]],
    book: PriceBook,
    window_name: str,
    as_of: date,
    history: list[dict[str, int]],
    min_trades: int,
    late_days: int,
    with_curve: bool,
) -> tuple[dict, dict[str, MemberCurve]]:
    rows: list[BoardRow] = []
    curves: dict[str, list] = {}
    for person in politicians:
        trades = trades_by_member.get(person.bioguide_id, [])
        stats = score_member(
            trades,
            book,
            window_name,
            as_of,
            late_days=late_days,
            with_curve=with_curve,
        )
        if with_curve:
            curves[person.bioguide_id] = stats.curve
        rows.append(
            BoardRow(
                bioguide_id=person.bioguide_id,
                name=person.name,
                initials=initials(person.name),
                chamber=person.chamber,
                party=person.party,
                state=person.state,
                district=person.district,
                years_in_service=person.years_in_service,
                stats=stats,
            )
        )
    ordered = order_rows(rows, min_trades)
    apply_history(ordered, history)
    assign_badges(ordered)
    payloads = []
    for row in ordered:
        payload = _row_payload(row)
        payload["top_ticker"] = _top_ticker(trades_by_member.get(row.bioguide_id, []), window_name, as_of)
        payloads.append(payload)
    ranked = [row for row in payloads if not row["benched"]]
    benched = [row for row in payloads if row["benched"]]
    beat = sum(1 for row in ranked if (row["alpha"] or 0) > 0.0001)
    tape_rows = payloads
    previous_date = None
    body = {
        "as_of": as_of.isoformat(),
        "previous_date": previous_date,
        "ranked": ranked,
        "benched": benched,
        "beat_market": beat,
        "field_size": len(ranked),
        "benched_size": len(benched),
        "ticker_tape": build_tape(
            window_name,
            tape_rows,
            min_trades,
            seed=f"{window_name}:{as_of.isoformat()}",
        ),
    }
    return body, curves


def _top_ticker(trades: list[Trade], window_name: str, as_of: date) -> str | None:
    start, end = window_bounds(window_name, as_of)
    totals: dict[str, float] = {}
    for trade in trades:
        if classify_asset(trade) != "equity" or side_of(trade.transaction_type) is None:
            continue
        if trade.transaction_date is None or not (start <= trade.transaction_date <= end):
            continue
        dollars, _how = midpoint(trade.amount_min, trade.amount_max)
        if dollars is None:
            continue
        totals[trade.symbol] = totals.get(trade.symbol, 0.0) + dollars
    if not totals:
        return None
    return max(totals, key=lambda symbol: (totals[symbol], symbol))


def member_document(
    person: Politician,
    trades: list[Trade],
    book: PriceBook,
    as_of: date,
    curves: dict[str, dict[str, list]],
    late_days: int,
) -> dict:
    rows = []
    for trade in sorted(trades, key=lambda item: (item.transaction_date or date.min, item.symbol), reverse=True):
        dollars, how = midpoint(trade.amount_min, trade.amount_max)
        lag = filing_lag_days(trade)
        kind = classify_asset(trade)
        rows.append(
            {
                "transaction_date": _iso(trade.transaction_date),
                "filed_date": _iso(trade.disclosure_date),
                "lag_days": lag,
                "late": bool(is_late(trade, late_days)),
                "side": side_of(trade.transaction_type) or trade.transaction_type,
                "symbol": trade.symbol,
                "asset_name": trade.asset_name,
                "asset_type_code": trade.asset_type_code,
                "amount_min": trade.amount_min,
                "amount_max": trade.amount_max,
                "midpoint": dollars,
                "midpoint_method": how,
                "owner_code": trade.owner_code,
                "included": kind == "equity" and side_of(trade.transaction_type) is not None,
                "exclude_reason": None if kind == "equity" else kind,
                "source_url": trade.source_url,
                "disclosure_portal": disclosure_portal(person.chamber),
            }
        )
    return {
        "bioguide_id": person.bioguide_id,
        "name": person.name,
        "initials": initials(person.name),
        "chamber": person.chamber,
        "party": person.party,
        "state": person.state,
        "district": person.district,
        "years_in_service": person.years_in_service,
        "curves": curves.get(person.bioguide_id, {}),
        "trades": rows,
    }


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def assemble_league(
    politicians: list[Politician],
    trades_by_member: dict[str, list[Trade]],
    book: PriceBook,
    as_of: date,
    history_by_window: dict[str, list[dict]],
    min_trades: int = 3,
    late_days: int = 45,
    sample: bool = False,
    price_mode: str = "unadjusted",
    notes: list[str] | None = None,
) -> tuple[dict, dict[str, dict], dict]:
    """Return league JSON, member documents, and updated rank history."""
    windows = {}
    curves_by_window: dict[str, dict[str, list]] = {}
    updated_history: dict[str, list[dict]] = {}
    for name in WINDOWS:
        prior = list(history_by_window.get(name) or [])
        prior = [snap for snap in prior if snap.get("as_of") != as_of.isoformat()]
        rank_maps = [snap.get("ranks") or {} for snap in prior]
        body, curves = build_window(
            politicians,
            trades_by_member,
            book,
            name,
            as_of,
            rank_maps,
            min_trades,
            late_days,
            with_curve=True,
        )
        if prior:
            body["previous_date"] = prior[-1].get("as_of")
        windows[name] = body
        curves_by_window[name] = curves
        today_ranks = {
            row["bioguide_id"]: row["rank"]
            for row in body["ranked"]
            if row["rank"] is not None
        }
        updated = prior + [{"as_of": as_of.isoformat(), "ranks": today_ranks}]
        updated_history[name] = updated[-40:]

    league = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "as_of": as_of.isoformat(),
        "sample": sample,
        "price_mode": price_mode,
        "min_trades": min_trades,
        "late_days": late_days,
        "attribution": ATTRIBUTION,
        "disclaimer": DISCLAIMER,
        "notes": notes or [],
        "windows": windows,
        "badges": BADGE_COPY,
    }
    members = {}
    for person in politicians:
        per_window = {name: curves_by_window[name].get(person.bioguide_id, []) for name in WINDOWS}
        members[person.bioguide_id] = member_document(
            person, trades_by_member.get(person.bioguide_id, []), book, as_of, {person.bioguide_id: per_window}, late_days
        )
        # Attach the window stats the table already computed so the page matches.
        members[person.bioguide_id]["windows"] = {}
        for name in WINDOWS:
            found = _find_row(windows[name], person.bioguide_id)
            if found:
                members[person.bioguide_id]["windows"][name] = {
                    key: found[key]
                    for key in (
                        "rank",
                        "previous_rank",
                        "rank_change",
                        "streak",
                        "on_fire",
                        "benched",
                        "return",
                        "alpha",
                        "benchmark",
                        "copycat_return",
                        "copycat_alpha",
                        "trades",
                        "avg_hold_days",
                        "avg_filing_lag",
                        "late_filings",
                        "filings",
                        "badges",
                        "excluded_options",
                        "excluded_non_stock",
                        "excluded_unknown",
                        "unmatched_sells",
                        "uncopyable",
                    )
                    if key in found
                }
    return league, members, updated_history


def _find_row(window: dict, bioguide_id: str) -> dict | None:
    for row in window["ranked"] + window["benched"]:
        if row["bioguide_id"] == bioguide_id:
            return row
    return None


def write_site(site_data: Path, league: dict, members: dict[str, dict], history: dict) -> None:
    site_data.mkdir(parents=True, exist_ok=True)
    member_dir = site_data / "members"
    member_dir.mkdir(parents=True, exist_ok=True)
    _dump(site_data / "league.json", league)
    _dump(site_data / "rank-history.json", history)
    index = []
    for bioguide_id, document in members.items():
        _dump(member_dir / f"{bioguide_id}.json", document)
        index.append(
            {
                "bioguide_id": bioguide_id,
                "name": document["name"],
                "chamber": document["chamber"],
                "party": document["party"],
                "state": document["state"],
            }
        )
    _dump(site_data / "members.json", {"members": index})
    # Remove member files that are no longer in this export.
    keep = {f"{bioguide_id}.json" for bioguide_id in members}
    for path in member_dir.glob("*.json"):
        if path.name not in keep:
            path.unlink()


def load_history(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")


def empty_history_from_snapshots(
    politicians: list[Politician],
    trades_by_member: dict[str, list[Trade]],
    book: PriceBook,
    as_of_dates: list[date],
    min_trades: int,
    late_days: int,
) -> dict[str, list[dict]]:
    """Build rank history by replaying earlier scoreboard dates. Oldest first.

    The last date should be the live as_of. It is not stored here; assemble_league
    appends it. Pass every date except the final one.
    """
    history: dict[str, list[dict]] = {name: [] for name in WINDOWS}
    for as_of in as_of_dates:
        for name in WINDOWS:
            rank_maps = [snap["ranks"] for snap in history[name]]
            body, _curves = build_window(
                politicians,
                trades_by_member,
                book,
                name,
                as_of,
                rank_maps,
                min_trades,
                late_days,
                with_curve=False,
            )
            history[name].append(
                {
                    "as_of": as_of.isoformat(),
                    "ranks": {row["bioguide_id"]: row["rank"] for row in body["ranked"]},
                }
            )
    return history

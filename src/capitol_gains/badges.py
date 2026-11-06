"""Badges from window stats. Party is not an input."""

from __future__ import annotations

from capitol_gains.models import BoardRow

BADGE_COPY = {
    "beat_the_market": {
        "name": "Beat the Market",
        "blurb": "Positive alpha versus SPY over the same holding periods.",
    },
    "market_beat_you": {
        "name": "The Market Beat You",
        "blurb": "Negative alpha versus SPY over the same holding periods.",
    },
    "index_hugger": {
        "name": "Index Hugger",
        "blurb": "Alpha landed within 2 percentage points of the S&P.",
    },
    "one_big_bet": {
        "name": "One Big Bet",
        "blurb": "The largest one or two trades are at least 70% of the dollars.",
    },
    "tech_bro": {
        "name": "Tech Bro",
        "blurb": "At least half the midpoint dollars sit in the technology list.",
    },
    "punctual_pro": {
        "name": "Punctual Pro",
        "blurb": "Every filing in this window landed inside 45 days.",
    },
    "diamond_hands": {
        "name": "Diamond Hands",
        "blurb": "Longest average holding period on the board.",
    },
    "paper_hands": {
        "name": "Paper Hands",
        "blurb": "Shortest average holding period on the board.",
    },
    "fashionably_late": {
        "name": "Fashionably Late",
        "blurb": "Highest average gap between the trade and the filing.",
    },
    "buy_high_sell_low": {
        "name": "Buy High Sell Low",
        "blurb": "Worst capital-weighted return on positions that were closed.",
    },
}


def assign_badges(rows: list[BoardRow]) -> None:
    for row in rows:
        row.badges = []
        stats = row.stats
        alpha = stats.their_alpha
        if alpha is None:
            continue
        # Ignore floating-point dust so a pure SPY clone is not "beating" the market.
        if alpha > 0.0001:
            row.badges.append("beat_the_market")
        elif alpha < -0.0001:
            row.badges.append("market_beat_you")
        if abs(alpha) <= 0.02:
            row.badges.append("index_hugger")
        if (
            stats.trade_count >= 3
            and stats.top_two_share is not None
            and stats.top_two_share >= 0.70
        ):
            row.badges.append("one_big_bet")
        if stats.tech_share is not None and stats.tech_share >= 0.50 and stats.trade_count >= 1:
            row.badges.append("tech_bro")
        if stats.filings >= 1 and stats.late_filings == 0 and stats.avg_filing_lag is not None:
            row.badges.append("punctual_pro")

    _award_extreme(rows, "diamond_hands", lambda r: r.stats.avg_hold_days, largest=True)
    _award_extreme(rows, "paper_hands", lambda r: r.stats.avg_hold_days, largest=False)
    _award_extreme(rows, "fashionably_late", lambda r: r.stats.avg_filing_lag, largest=True)
    _award_extreme(rows, "buy_high_sell_low", lambda r: r.stats.realized_return, largest=False)


def _award_extreme(rows: list[BoardRow], badge: str, value, largest: bool) -> None:
    pool = [(value(row), row) for row in rows if value(row) is not None]
    if not pool:
        return
    pool.sort(key=lambda item: (-item[0] if largest else item[0], item[1].name))
    pool[0][1].badges.append(badge)

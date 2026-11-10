"""Every ticker-tape line has to render, and none of them use a banned word."""

from capitol_street_bets.commentary import (
    BANNED_WORDS,
    PLACEHOLDERS,
    TEMPLATES,
    banned_hits,
    build_tape,
    render_template,
    template_placeholders,
)


def _context() -> dict[str, str]:
    return {key: f"v-{key}" for key in PLACEHOLDERS}


def test_template_catalog_is_large_and_complete():
    assert len(TEMPLATES) >= 100
    assert len(BANNED_WORDS) >= 10
    context = _context()
    seen = set()
    for category, text in TEMPLATES:
        assert category
        assert text not in seen
        seen.add(text)
        unknown = template_placeholders(text) - PLACEHOLDERS
        assert unknown == set()
        rendered = render_template(text, context)
        assert "{" not in rendered
        assert banned_hits(text) == []
        assert banned_hits(rendered) == []


def test_missing_placeholder_is_an_error():
    try:
        render_template("{name} climbs {spots}", {"name": "Ada"})
    except KeyError:
        return
    raise AssertionError("missing placeholder should fail")


def test_built_tape_stays_clean():
    rows = [
        {
            "name": "Ada Example",
            "benched": False,
            "rank": 1,
            "previous_rank": 4,
            "rank_change": 3,
            "took_first": True,
            "on_fire": True,
            "streak": 3,
            "alpha": 0.04,
            "return": 0.08,
            "copycat_return": 0.02,
            "avg_filing_lag": 12,
            "avg_hold_days": 40,
            "trades": 6,
            "badges": ["punctual_pro", "one_big_bet"],
            "chamber": "House",
            "top_ticker": "AAPL",
        },
        {
            "name": "Bea Example",
            "benched": True,
            "rank": None,
            "rank_change": None,
            "alpha": -0.03,
            "return": -0.01,
            "copycat_return": -0.02,
            "avg_filing_lag": 70,
            "avg_hold_days": 5,
            "trades": 1,
            "badges": [],
            "chamber": "Senate",
            "top_ticker": "XOM",
        },
    ]
    lines = build_tape("30d", rows, min_trades=3, seed="2026-11-06")
    assert len(lines) >= 8
    for line in lines:
        assert "{" not in line
        assert banned_hits(line) == []

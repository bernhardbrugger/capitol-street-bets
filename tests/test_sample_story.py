"""The shipped sample league has to be fun, and obviously fictional."""

from capitol_street_bets.commentary import banned_hits
from capitol_street_bets.league import DISCLAIMER, ATTRIBUTION
from capitol_street_bets.sample_league import build_sample


def test_sample_board_has_the_set_pieces():
    league, members, _history = build_sample()
    assert league["sample"] is True
    assert league["disclaimer"] == DISCLAIMER
    assert league["attribution"] == ATTRIBUTION
    window = league["windows"]["30d"]
    rows = window["ranked"] + window["benched"]
    assert any(row["on_fire"] for row in window["ranked"])
    assert any(row["elevator"] for row in window["ranked"])
    assert any(row["took_first"] for row in window["ranked"])
    assert window["benched"]
    badges = {badge["id"] for row in rows for badge in row["badges"]}
    for required in (
        "diamond_hands",
        "paper_hands",
        "fashionably_late",
        "buy_high_sell_low",
        "index_hugger",
        "one_big_bet",
        "tech_bro",
        "punctual_pro",
        "beat_the_market",
        "market_beat_you",
    ):
        assert required in badges
    assert {row["chamber"] for row in rows} >= {"House", "Senate"}
    assert {row["party"] for row in rows} >= {"D", "R", "I"}
    for line in window["ticker_tape"]:
        assert "{" not in line
        assert banned_hits(line) == []
    jordan = members["CG0001"]
    assert jordan["trades"]
    assert "source_url" in jordan["trades"][0]
    assert jordan["curves"]["30d"]
    assert any(trade["exclude_reason"] == "option" for trade in jordan["trades"])

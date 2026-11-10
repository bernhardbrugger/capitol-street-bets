import json

from capitol_street_bets.readme_board import END, START, render, update_readme
from pathlib import Path


def test_render_marks_sample_and_links_members(tmp_path):
    from capitol_street_bets.sample_league import write_sample

    league = write_sample(tmp_path)
    text = render(league, "https://example.test/board/")
    assert "Sample data" in text
    assert "https://example.test/board/#/member/" in text
    assert "| 1 |" in text


def test_update_is_idempotent(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"# x\n\n{START}\nold\n{END}\n\ntail\n")
    league = tmp_path / "league.json"
    league.write_text(json.dumps({"sample": False, "generated_at": "2026-11-10T00:00:00", "windows": {}}))
    assert update_readme(readme, league, "https://e.test/") is True
    assert "tail" in readme.read_text() and "old" not in readme.read_text()
    assert update_readme(readme, league, "https://e.test/") is False


def test_recent_disclosures_cap_one_busy_filer():
    from datetime import date

    from capitol_street_bets.league import recent_disclosures
    from capitol_street_bets.models import Politician, Trade

    def trade(bid, sym, day):
        return Trade(bid, sym, "BUY", date(2026, 10, day), date(2026, 10, day + 2), None, 1001.0, 15000.0, f"{sym} [ST]", "ST", "SELF", None)

    people = [Politician("A1", "Busy", "House", "R", "TX", "1", [], 1.0), Politician("B2", "Calm", "House", "D", "CA", "2", [], 1.0)]
    grouped = {"A1": [trade("A1", f"T{i}", 1 + i) for i in range(6)], "B2": [trade("B2", "NVDA", 1)]}
    rows = recent_disclosures(people, grouped, date(2026, 11, 1))
    assert [r["bioguide_id"] for r in rows].count("A1") == 2
    assert any(r["bioguide_id"] == "B2" for r in rows)

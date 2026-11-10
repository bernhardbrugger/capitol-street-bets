import json

from capitol_gains.readme_board import END, START, render, update_readme
from pathlib import Path


def test_render_marks_sample_and_links_members(tmp_path):
    league = json.loads((Path(__file__).parents[1] / "web/public/data/league.json").read_text())
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

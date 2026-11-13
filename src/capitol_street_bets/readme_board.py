"""Write the current top of the league into README.md between two markers.

The daily workflow runs this after scoring, so the repo page itself shows
the standings without anyone opening the site.
"""

from __future__ import annotations

import json
from pathlib import Path

START = "<!-- LEADERBOARD:START -->"
END = "<!-- LEADERBOARD:END -->"
WINDOW_ORDER = ("12m", "6m", "90d", "all", "30d")
WINDOW_LABEL = {
    "12m": "last 12 months",
    "6m": "last 6 months",
    "90d": "last 90 days",
    "ytd": "year to date",
    "all": "all time",
    "30d": "last 30 days",
}


def _pct(value) -> str:
    if value is None:
        return "–"
    return f"{value * 100:+.1f}%"


def _money(value: float) -> str:
    if value >= 1e6:
        return f"${value / 1e6:.1f}M"
    if value >= 1e3:
        return f"${round(value / 1e3)}K"
    return f"${round(value)}"


def _arrow(row: dict) -> str:
    change = row.get("rank_change")
    if row.get("previous_rank") is None:
        return "🆕"
    if not change:
        return "▬"
    return f"▲{change}" if change > 0 else f"▼{abs(change)}"


def _seat(row: dict) -> str:
    chamber = (row.get("chamber") or "")[:1].upper()
    party = row.get("party") or "?"
    state = row.get("state") or ""
    return f"{party}-{state} · {chamber}" if chamber else f"{party}-{state}"


def render(league: dict, site_url: str, top: int = 10) -> str:
    windows = league.get("windows", {})
    key = next((k for k in WINDOW_ORDER if windows.get(k, {}).get("ranked")), None)
    lines: list[str] = []
    if league.get("sample"):
        lines.append(
            "> ⚠️ **Sample data.** These names and numbers are fictional. "
            "The board switches to live disclosures after the first successful data refresh."
        )
        lines.append("")
    if key is None:
        lines.append("_Preseason: no member has enough priced trades to be ranked yet. The board fills up with every refresh._")
        recent = league.get("recent_disclosures") or []
        if recent:
            lines.append("")
            lines.append("**Latest disclosures**")
            lines.append("")
            lines.append("| Filed | Member | | Ticker | Amount | Filed after |")
            lines.append("|---|---|:---:|---|---:|---:|")
            for item in recent[:6]:
                lag = item.get("lag_days")
                lag_text = "–" if lag is None else f"{lag} days" + (" ⚠️" if item.get("late") else "")
                lines.append(
                    "| {filed} | [{name}]({url}#/member/{bid}) | {side} | **{sym}** | {amt} | {lag} |".format(
                        filed=item.get("filed_date", ""),
                        name=item.get("name", ""),
                        url=site_url,
                        bid=item.get("bioguide_id", ""),
                        side="🟢 Buy" if item.get("side") == "buy" else "🔴 Sell",
                        sym=item.get("symbol", ""),
                        amt=item.get("amount", ""),
                        lag=lag_text,
                    )
                )
    else:
        window = windows[key]
        lines.append(f"**Top {min(top, len(window['ranked']))}, {WINDOW_LABEL[key]}** (as of {window.get('as_of') or league.get('as_of')})")
        lines.append("")
        lines.append("| # | | Member | Seat | Return | Alpha vs S&P | Copycat | Trades |")
        lines.append("|---:|:---:|---|---|---:|---:|---:|---:|")
        for row in window["ranked"][:top]:
            lines.append(
                "| {rank} | {arrow} | [{name}]({url}#/member/{bid}) | {seat} | {ret} | **{alpha}** | {copy} | {trades} |".format(
                    rank=row.get("rank", ""),
                    arrow=_arrow(row),
                    name=row.get("name", row.get("bioguide_id", "")),
                    url=site_url,
                    bid=row.get("bioguide_id", ""),
                    seat=_seat(row),
                    ret=_pct(row.get("return")),
                    alpha=_pct(row.get("alpha")),
                    copy=_pct(row.get("copycat_return")),
                    trades=row.get("trades", ""),
                )
            )
    stock_key = next((k for k in WINDOW_ORDER if windows.get(k, {}).get("most_traded")), None)
    if stock_key:
        lines.append("")
        lines.append(f"**Most traded stocks, {WINDOW_LABEL[stock_key]}**")
        lines.append("")
        lines.append("| # | Ticker | Trades | Members | Buys / sells | Est. volume | Move |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|")
        for index, stock in enumerate(windows[stock_key]["most_traded"][:5], start=1):
            lines.append(
                "| {i} | [**{sym}**]({url}#/stocks?s={sym}) | {t} | {m} | {b} / {sl} | ~{vol} | {mv} |".format(
                    i=index,
                    sym=stock["symbol"],
                    url=site_url,
                    t=stock["trades"],
                    m=stock["members"],
                    b=stock["buys"],
                    sl=stock["sells"],
                    vol=_money(stock.get("est_dollars") or 0),
                    mv=_pct(stock.get("price_change")),
                )
            )
    coverage = league.get("coverage")
    lines.append("")
    if coverage and coverage.get("members_seated"):
        lines.append(
            f"Members loaded so far: **{coverage['members_loaded']} of {coverage['members_seated']}** seated. "
            f"Updated {str(league.get('generated_at', ''))[:10]}. [Full board →]({site_url})"
        )
    else:
        lines.append(f"Updated {str(league.get('generated_at', ''))[:10]}. [Full board →]({site_url})")
    return "\n".join(lines)


def update_readme(readme: Path, league_path: Path, site_url: str, top: int = 10) -> bool:
    league = json.loads(league_path.read_text())
    block = f"{START}\n{render(league, site_url, top)}\n{END}"
    text = readme.read_text()
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        new = head + block + tail
    else:
        new = text.rstrip() + "\n\n## Current standings\n\n" + block + "\n"
    if new == text:
        return False
    readme.write_text(new)
    return True

"""Daily ticker tape. Templates talk about stats, never about a person.

Every template has to render from the placeholder set below. The unit test
also scans the whole list for banned words.
"""

from __future__ import annotations

import hashlib
import random
import re

PLACEHOLDERS = {
    "name",
    "lag",
    "spots",
    "return_pct",
    "alpha_pct",
    "ticker",
    "chamber",
    "days",
    "streak",
    "trades",
    "rank",
    "count",
    "window",
    "min_trades",
    "hold_days",
    "side",
    "copy_pct",
}

BANNED_WORDS = (
    "insider",
    "corrupt",
    "corruption",
    "crime",
    "criminal",
    "illegal",
    "crook",
    "crooked",
    "thief",
    "fraud",
    "fraudulent",
    "bribe",
    "bribery",
    "scam",
    "scandal",
    "prison",
    "jail",
    "felony",
    "cheat",
    "ugly",
    "idiot",
    "stupid",
    "senile",
    "traitor",
    "democrat",
    "republican",
    "liberal",
    "conservative",
    "maga",
    "woke",
    "grifter",
    "sellout",
    "launder",
    "steal",
    "stolen",
    "dementia",
    "bald",
)

BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(word) for word in BANNED_WORDS) + r")\b", re.I)
PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# category, text. Placeholders are filled from that day's stats.
TEMPLATES: list[tuple[str, str]] = [
    ("climb", "{name} climbs {spots} spots. Somebody's been reading earnings calls."),
    ("climb", "{name} moves up {spots}. The standings just got more interesting."),
    ("climb", "{name} picks up {spots} places. The replay is worth a second look."),
    ("climb", "Up {spots} for {name}. That is a real change of address on the table."),
    ("climb", "{name} climbs {spots} and the rest of the board slides over."),
    ("climb", "{name} is {spots} spots higher. The holding periods did the talking."),
    ("climb", "A {spots}-spot climb for {name}. No parade, just a better rank."),
    ("climb", "{name} jumps {spots}. The S&P comparison came back smiling."),
    ("climb", "{name} gains {spots} places. File this one under 'the numbers moved'."),
    ("climb", "{name} rises {spots} spots. The league table has a new traffic pattern."),
    ("climb", "Make room: {name} is up {spots}. Same rules, better week."),
    ("climb", "{name} climbs {spots}. Somewhere a spreadsheet feels appreciated."),
    ("climb", "{name} advances {spots} places. The arrow is green and it means it."),
    ("climb", "Rank check: {name} is {spots} higher than last snapshot."),
    ("climb", "{name} takes {spots} steps up the table. Shoes optional, math required."),
    ("climb", "{name} is climbing, {spots} spots at a time. The streak watch begins."),
    ("drop", "{name} drops {spots} spots. That was less of a dip and more of an elevator shaft."),
    ("drop", "{name} falls {spots} places. The benchmark kept walking."),
    ("drop", "Down {spots} for {name}. The table does not do sympathy cards."),
    ("drop", "{name} slides {spots} spots. Mark-to-market had opinions."),
    ("drop", "{name} loses {spots} places. Same holding-period rules, tougher print."),
    ("drop", "A {spots}-spot drop for {name}. The arrow is not being subtle."),
    ("drop", "{name} is {spots} spots lower. The replay is mostly red candles."),
    ("drop", "{name} gives back {spots} places. The S&P did not wait around."),
    ("drop", "Elevator down: {name} falls {spots}. Mind the closing doors."),
    ("drop", "{name} drops {spots}. The league calls that a plot twist, not a verdict."),
    ("drop", "{name} moves down {spots} spots. Yesterday's rank called. It moved out."),
    ("drop", "{name} sheds {spots} places. The position sizes were estimates. The direction was not."),
    ("drop", "Big swing down for {name}: {spots} spots. The tape is taking notes."),
    ("drop", "{name} is off {spots}. Still a public filing, still just a scoreboard."),
    ("drop", "{name} falls {spots} and the confetti stays in the jar."),
    ("drop", "The board reshuffles. {name} is {spots} spots softer."),
    ("first", "New leader: {name}. The rest of the league is studying the replay."),
    ("first", "{name} takes the top spot. Somebody order a small, tasteful celebration."),
    ("first", "Number one today is {name}. The trophy is imaginary and the math is not."),
    ("first", "{name} reaches rank 1. The previous leader has been asked to clap politely."),
    ("first", "Top of the table: {name}. Alpha versus the S&P got them there."),
    ("first", "{name} is alone at the top. The view is just a better holding-period print."),
    ("first", "The chair at #1 has a new name on it: {name}."),
    ("first", "{name} grabs first place. Confetti is complimentary. Advice is not."),
    ("first", "Rank 1, {name}. The league remains undefeated at filing paperwork."),
    ("first", "{name} is the new leader. Same benchmark, sharper stretch."),
    ("streak", "{name} is on a {streak}-day climb. The ladder called. It is impressed."),
    ("streak", "{name} has climbed {streak} snapshots in a row. That is a streak, not a slogan."),
    ("streak", "On fire: {name}, up the table {streak} days running."),
    ("streak", "{name} keeps climbing. {streak} straight improvements."),
    ("streak", "The arrow next to {name} has worked {streak} days without a day off."),
    ("streak", "{name} is riding a {streak}-day run. The scoreboard brought a match."),
    ("streak", "{streak} up days for {name}. Somebody check the holding periods. They check out."),
    ("streak", "{name} has a {streak}-snapshot heater. Enjoy it at the speed of filings."),
    ("streak", "Streak watch: {name} at {streak}. The table is keeping count."),
    ("streak", "{name} climbs again. That makes {streak} in a row."),
    ("late", "{name} filed {lag} days late. The STOCK Act called. It wants its deadline back."),
    ("late", "{name} showed up {lag} days after the trade. Fashionably is doing a lot of work there."),
    ("late", "Filing lag for {name}: {lag} days. The deadline was not a suggestion, but here we are."),
    ("late", "{name} posted a {lag}-day gap between trade and filing. The calendar noticed."),
    ("late", "{lag} days from trade to filing for {name}. Copycats had a long wait."),
    ("late", "{name} and the clock are not on speaking terms. Average lag: {lag} days."),
    ("late", "Late slip of {lag} days for {name}. The disclosure still counts. The timing is the bit."),
    ("late", "{name} filed {lag} days after the transaction. Punctuality is a skill tree."),
    ("late", "The inbox of {name} delivered in {lag} days. The league expected 45 or less."),
    ("late", "{name} averaged {lag} days to file. That is a long walk from the trade date."),
    ("late", "Disclosure delay, {name}: {lag} days. Mark it late and move on."),
    ("late", "{name} cleared the 45-day line by landing at {lag}. The flag is informational."),
    ("punctual", "{name} filed inside the window. Average lag {lag} days. Punctual looks good on anyone."),
    ("punctual", "On time: {name}, about {lag} days from trade to filing."),
    ("punctual", "{name} kept the filings inside 45 days. The badge is Punctual Pro, the tone is relieved."),
    ("punctual", "{name} did not make the deadline sweat. Lag: {lag} days."),
    ("punctual", "Clock this: {name} averaged {lag} days and stayed inside the line."),
    ("punctual", "{name} filed with {lag} days to spare on the average. The STOCK Act can unclench."),
    ("punctual", "Punctual print for {name}. {lag} days, no late flag in this window."),
    ("punctual", "{name} treated 45 days as a ceiling, not a suggestion. Average {lag}."),
    ("beat", "{count} members beat SPY in the {window} window. The benchmark brought its shoes."),
    ("beat", "Congress versus the market, {window}: {count} ahead of SPY."),
    ("beat", "Scoreboard check. {count} members have positive alpha over {window}."),
    ("beat", "The S&P gave up {count} wins in the {window} view. It will want a rematch."),
    ("beat", "{count} positive alphas in {window}. The rest are negotiating with the index."),
    ("beat", "Market check, {window}: {count} members are in front of SPY."),
    ("beat", "A {window} look: {count} members cleared the benchmark. Applause is optional."),
    ("beat", "{count} beat the S&P over {window}. The holding periods were matched on purpose."),
    ("lag_market", "{name} is behind SPY by {alpha_pct}. Gravity still works."),
    ("lag_market", "The market leads {name} by {alpha_pct}. Same dates, different result."),
    ("lag_market", "{name} trails the benchmark by {alpha_pct}. The Market Beat You badge is in the mail."),
    ("lag_market", "Alpha for {name}: {alpha_pct}. The S&P did not send a gift basket."),
    ("lag_market", "{name} versus SPY is {alpha_pct}. The index hug is not mutual."),
    ("lag_market", "{name} gave the benchmark a {alpha_pct} head start and did not catch up."),
    ("lag_market", "SPY had the better calendar than {name}, by {alpha_pct}."),
    ("lag_market", "{name} prints {alpha_pct} against the S&P. The chart is allowed to be honest."),
    ("hugger", "{name} is hugging the index, alpha {alpha_pct}. A participation ribbon, lightly starched."),
    ("hugger", "{name} finished within a whisper of SPY ({alpha_pct}). Index Hugger energy."),
    ("hugger", "Close to the benchmark: {name} at {alpha_pct}. The S&P considers this a draw."),
    ("hugger", "{name} tracked SPY to {alpha_pct}. Parallel parking, but for portfolios."),
    ("hugger", "Alpha {alpha_pct} for {name}. That is basically the index in a different jacket."),
    ("hugger", "{name} stayed inside the plus-or-minus 2% lane. Alpha {alpha_pct}."),
    ("hands", "{name} held about {hold_days} days on average. Diamond hands, or a very calm inbox."),
    ("hands", "Average hold for {name}: {hold_days} days. The lots were not in a hurry."),
    ("hands", "{name} let positions sit {hold_days} days. The badge committee is watching."),
    ("hands", "{name} turned positions over in about {hold_days} days. Paper, possibly recycled."),
    ("hands", "Holding period, {name}: {hold_days} days. Long enough to need a labeled folder."),
    ("hands", "{name} averaged {hold_days} days in the trade. The FIFO ledger approves of patience."),
    ("hands", "Short stay: {name} at {hold_days} days. Hello, goodbye, next disclosure."),
    ("hands", "{name} and the calendar spent {hold_days} days together. One of them blinked."),
    ("bet", "{name} put most of the dollars into one or two tickets. {trades} trades, concentrated."),
    ("bet", "One Big Bet check: {name}, {trades} trades, and the top of the book did the heavy lifting."),
    ("bet", "{name} did not sprinkle. {trades} trades, most of the midpoint in a couple of lines."),
    ("bet", "Concentration alert, the fun kind: {name} with {trades} disclosed trades."),
    ("bet", "{name} let one or two positions carry the dollar weight across {trades} trades."),
    ("bet", "The volume clustered for {name}. {trades} trades, not a sampler platter."),
    ("benched", "{name} is benched until more priced equity trades show up. The minimum is {min_trades}."),
    ("benched", "{name} has {trades} qualifying trades in this window. The lineup wants {min_trades}."),
    ("benched", "Bench note: {name} is listed, not ranked. {trades} trades so far."),
    ("benched", "{name} stays on the bench with {trades} trades. The threshold is {min_trades}, not a vibe."),
    ("benched", "No rank yet for {name}. {trades} of {min_trades} priced equity trades in the window."),
    ("benched", "{name} is warming up on the bench. Trade count: {trades}."),
    ("score", "Their return for {name}: {return_pct}. Copycat return: {copy_pct}."),
    ("score", "{name} shows {return_pct} on transaction-date entries and {copy_pct} if you waited to copy."),
    ("score", "Two clocks, one member. {name}: {return_pct} theirs, {copy_pct} for the copycats."),
    ("score", "{name} in the {chamber}: return {return_pct}, alpha {alpha_pct}."),
    ("score", "{chamber} check. {name} is at rank {rank} with alpha {alpha_pct}."),
    ("score", "{name} logged {trades} priced equity trades. Return {return_pct}."),
    ("score", "Window {window}: {name} at {return_pct} versus a matched SPY path."),
    ("score", "{name} rank {rank}. Alpha {alpha_pct}. The footnote is the methodology page."),
    ("tape", "Welcome back to the only league where the lineup files the box score later."),
    ("tape", "Ranges, not receipts. Every dollar on this board is a midpoint with a straight face."),
    ("tape", "SPY is on the field too. Nobody gets a custom benchmark."),
    ("tape", "Buys open the lot. Sales close it FIFO. Leftovers get marked to today."),
    ("tape", "Options and mystery tickers sit out and get counted. The scoreboard likes a paper trail."),
    ("tape", "Copycat mode starts on the disclosure date. If it was closed before that, you missed it."),
    ("tape", "Rank needs {min_trades} priced equity trades in the window. Otherwise: benched."),
    ("tape", "Party is a label on the card. It is not in the formula, the badges, or this tape."),
    ("tape", "Late means more than 45 days from trade to filing. It is a timer, not a gavel."),
    ("tape", "The {window} window is selected. Arrows compare it with the previous snapshot."),
    ("tape", "Alpha is their return minus SPY over the same dates. Apples, meet apples."),
    ("tape", "Unmatched sales stay unmatched. This board does not invent a position it cannot see."),
    ("fresh", "New filing energy around {name}. Lag on the latest average: {lag} days."),
    ("fresh", "{name} has fresh paperwork in the {window} window. {trades} priced trades beside it."),
    ("fresh", "The tape sees {name} at rank {rank} after the latest shuffle."),
    ("fresh", "{name} just became part of the {window} conversation. Return {return_pct}."),
    ("fresh", "Update on {name}: alpha {alpha_pct}, hold about {hold_days} days."),
    ("fresh", "{ticker} is doing a lot of the work in {name}'s book this window."),
    ("fresh", "{name} ({chamber}) sits at {return_pct}. The copycat column says {copy_pct}."),
    ("fresh", "If you copied {name} on the filing date, the screen says {copy_pct}."),
    ("fresh", "{name} closed the timing exam at {return_pct}. The class average is SPY."),
    ("fresh", "Holding-period alpha for {name} is {alpha_pct}. Window: {window}."),
]


def template_placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def render_template(text: str, context: dict[str, str]) -> str:
    missing = template_placeholders(text) - set(context)
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    unknown = template_placeholders(text) - PLACEHOLDERS
    if unknown:
        raise KeyError("unknown placeholder: " + ", ".join(sorted(unknown)))
    return text.format(**context)


def banned_hits(text: str) -> list[str]:
    return [match.group(0) for match in BANNED_RE.finditer(text)]


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f}%"


def _num(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if digits == 0:
        return str(int(round(value)))
    return f"{value:.{digits}f}"


def build_tape(window_name: str, rows: list[dict], min_trades: int, seed: str, limit: int = 14) -> list[str]:
    """Pick a stable set of lines for one window. Same seed, same tape."""
    by_cat: dict[str, list[str]] = {}
    for category, text in TEMPLATES:
        by_cat.setdefault(category, []).append(text)

    ranked = [row for row in rows if not row.get("benched")]
    climbers = [row for row in ranked if (row.get("rank_change") or 0) >= 3]
    fallers = [row for row in ranked if (row.get("rank_change") or 0) <= -3]
    leaders = [row for row in ranked if row.get("took_first")]
    streaks = [row for row in ranked if row.get("on_fire")]
    laggards = [
        row
        for row in rows
        if row.get("avg_filing_lag") is not None and row["avg_filing_lag"] > 45
    ]
    punctual = [row for row in rows if "punctual_pro" in row.get("badges", [])]
    huggers = [row for row in rows if "index_hugger" in row.get("badges", [])]
    trailers = [row for row in ranked if (row.get("alpha") or 0) < 0]
    bets = [row for row in rows if "one_big_bet" in row.get("badges", [])]
    hands = [row for row in rows if row.get("avg_hold_days") is not None]
    benched = [row for row in rows if row.get("benched")]
    beaters = [row for row in ranked if (row.get("alpha") or 0) > 0]

    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))

    def ctx(row: dict | None) -> dict[str, str]:
        source = row or {}
        return {
            "name": str(source.get("name") or "A member"),
            "lag": _num(source.get("avg_filing_lag")),
            "spots": _num(abs(source.get("rank_change") or 0)),
            "return_pct": _pct(source.get("return")),
            "alpha_pct": _pct(source.get("alpha")),
            "ticker": str(source.get("top_ticker") or "the book"),
            "chamber": str(source.get("chamber") or "Chamber"),
            "days": _num(source.get("avg_hold_days")),
            "streak": _num(source.get("streak")),
            "trades": _num(source.get("trades")),
            "rank": _num(source.get("rank") or 0),
            "count": str(len(beaters)),
            "window": window_name,
            "min_trades": str(min_trades),
            "hold_days": _num(source.get("avg_hold_days")),
            "side": "buy",
            "copy_pct": _pct(source.get("copycat_return")),
        }

    plan: list[tuple[str, dict | None]] = []
    if leaders:
        plan.append(("first", leaders[0]))
    for row in climbers[:2]:
        plan.append(("climb", row))
    for row in fallers[:2]:
        plan.append(("drop", row))
    for row in streaks[:2]:
        plan.append(("streak", row))
    for row in laggards[:2]:
        plan.append(("late", row))
    if punctual:
        plan.append(("punctual", punctual[0]))
    plan.append(("beat", None))
    if trailers:
        plan.append(("lag_market", trailers[0]))
    if huggers:
        plan.append(("hugger", huggers[0]))
    if hands:
        plan.append(("hands", max(hands, key=lambda row: row.get("avg_hold_days") or 0)))
        plan.append(("hands", min(hands, key=lambda row: row.get("avg_hold_days") or 0)))
    if bets:
        plan.append(("bet", bets[0]))
    if benched:
        plan.append(("benched", benched[0]))
    if ranked:
        plan.append(("score", ranked[0]))
        plan.append(("fresh", ranked[min(1, len(ranked) - 1)]))
    plan.append(("tape", None))
    plan.append(("tape", None))

    lines: list[str] = []
    used: set[str] = set()
    for category, row in plan:
        choices = [text for text in by_cat.get(category, []) if text not in used]
        if not choices:
            continue
        text = rng.choice(choices)
        used.add(text)
        lines.append(render_template(text, ctx(row)))
        if len(lines) >= limit:
            break
    filler_cats = ["tape", "score", "fresh", "beat"]
    while len(lines) < min(limit, 8):
        category = filler_cats[len(lines) % len(filler_cats)]
        choices = by_cat.get(category) or by_cat["tape"]
        text = choices[len(lines) % len(choices)]
        row = ranked[len(lines) % len(ranked)] if ranked else None
        rendered = render_template(text, ctx(row))
        if rendered not in lines:
            lines.append(rendered)
        else:
            break
    return lines

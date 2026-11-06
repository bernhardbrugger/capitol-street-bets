"""Ranks, arrows, and on-fire streaks across daily snapshots."""

from __future__ import annotations

from capitol_gains.models import BoardRow

ON_FIRE_DAYS = 3
ELEVATOR_DROP = 5


def order_rows(rows: list[BoardRow], min_trades: int) -> list[BoardRow]:
    """Rank eligible members by alpha. Everyone else is benched, in name order."""
    eligible = []
    benched = []
    for row in rows:
        ready = (
            row.stats.trade_count >= min_trades
            and row.stats.their_alpha is not None
            and row.stats.their_return is not None
        )
        if ready:
            eligible.append(row)
        else:
            row.benched = True
            row.rank = None
            benched.append(row)
    eligible.sort(
        key=lambda row: (
            -(row.stats.their_alpha or 0.0),
            -(row.stats.their_return or 0.0),
            row.name,
        )
    )
    for index, row in enumerate(eligible, start=1):
        row.rank = index
        row.benched = False
    benched.sort(key=lambda row: row.name)
    return eligible + benched


def apply_history(
    rows: list[BoardRow],
    history: list[dict[str, int]],
) -> None:
    """history is oldest-first snapshots of bioguide_id -> rank, not including today."""
    previous = history[-1] if history else {}
    for row in rows:
        if row.rank is None:
            row.previous_rank = previous.get(row.bioguide_id)
            row.rank_change = None
            row.streak = 0
            row.on_fire = False
            row.took_first = False
            continue
        prev = previous.get(row.bioguide_id)
        row.previous_rank = prev
        row.rank_change = None if prev is None else prev - row.rank
        row.streak = streak_length(row.bioguide_id, history, row.rank)
        row.on_fire = row.streak >= ON_FIRE_DAYS
        row.took_first = row.rank == 1 and prev is not None and prev != 1


def streak_length(bioguide_id: str, history: list[dict[str, int]], today_rank: int) -> int:
    """Consecutive strict improvements ending today. A tie or a drop resets."""
    sequence: list[int | None] = [snap.get(bioguide_id) for snap in history]
    sequence.append(today_rank)
    streak = 0
    for prev, curr in zip(sequence, sequence[1:]):
        if prev is None or curr is None or curr >= prev:
            streak = 0
            continue
        streak += 1
    return streak


def is_elevator(rank_change: int | None) -> bool:
    return rank_change is not None and rank_change <= -ELEVATOR_DROP

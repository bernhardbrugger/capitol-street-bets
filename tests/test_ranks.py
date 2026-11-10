"""Rank arrows and streaks across two snapshots, plus one longer run."""

from capitol_street_bets.models import BoardRow, MemberStats
from capitol_street_bets.ranks import apply_history, order_rows, streak_length


def _row(bioguide: str, name: str, alpha: float, trades: int = 3) -> BoardRow:
    return BoardRow(
        bioguide_id=bioguide,
        name=name,
        initials=name[:2].upper(),
        chamber="House",
        party="D",
        state="CA",
        district="1",
        years_in_service=1.0,
        stats=MemberStats(their_return=alpha, their_alpha=alpha, trade_count=trades),
    )


def test_rank_change_between_two_snapshots():
    yesterday = {"B": 1, "A": 2, "C": 3}
    rows = order_rows(
        [
            _row("A", "Ada", 0.20),
            _row("B", "Bea", 0.10),
            _row("C", "Cy", 0.00),
            _row("D", "Dee", 0.50, trades=1),
        ],
        min_trades=3,
    )
    apply_history(rows, [yesterday])
    by_id = {row.bioguide_id: row for row in rows}
    # Today: Ada, Bea, Cy. Yesterday Bea was 1 and Ada was 2.
    assert by_id["A"].rank == 1
    assert by_id["A"].rank_change == 1
    assert by_id["A"].took_first is True
    assert by_id["B"].rank == 2
    assert by_id["B"].rank_change == -1
    assert by_id["C"].rank_change == 0
    assert by_id["D"].benched is True
    assert by_id["D"].rank is None
    assert by_id["D"].rank_change is None


def test_streak_counts_only_strict_improvements():
    history = [
        {"A": 5, "B": 1},
        {"A": 4, "B": 2},
        {"A": 4, "B": 3},
        {"A": 2, "B": 4},
    ]
    # A: 5→4 improves, 4→4 resets, 4→2 improves, 2→1 improves. Streak ends at 2.
    assert streak_length("A", history, today_rank=1) == 2
    # B fell every day, including today.
    assert streak_length("B", history, today_rank=5) == 0
    rows = order_rows([_row("A", "Ada", 0.3), _row("B", "Bea", 0.1)], min_trades=3)
    # order is Ada then Bea, so today's ranks are 1 and 2, not the story above.
    # Feed history that makes Ada's last three steps a climb into rank 1.
    apply_history(rows, [{"A": 4}, {"A": 3}, {"A": 2}])
    ada = next(row for row in rows if row.bioguide_id == "A")
    assert ada.rank == 1
    assert ada.streak == 3
    assert ada.on_fire is True

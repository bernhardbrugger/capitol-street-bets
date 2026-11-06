"""Close lookup. A missing symbol, or a gap longer than the tolerance, is unknown."""

from __future__ import annotations

import bisect
from datetime import date


class PriceBook:
    def __init__(self, series: dict[str, dict[date, float]], max_gap_days: int = 7):
        self.max_gap_days = max_gap_days
        self.series: dict[str, dict[date, float]] = {}
        self._dates: dict[str, list[date]] = {}
        for symbol, points in series.items():
            self.add(symbol, points)

    def add(self, symbol: str, points: dict[date, float]) -> None:
        key = symbol.upper()
        bucket = self.series.setdefault(key, {})
        bucket.update(points)
        self._dates[key] = sorted(bucket)

    def symbols(self) -> list[str]:
        return sorted(self.series)

    def on_or_before(self, symbol: str, day: date) -> float | None:
        key = symbol.upper()
        dates = self._dates.get(key)
        if not dates:
            return None
        idx = bisect.bisect_right(dates, day) - 1
        if idx < 0:
            return None
        found = dates[idx]
        if (day - found).days > self.max_gap_days:
            return None
        return self.series[key][found]

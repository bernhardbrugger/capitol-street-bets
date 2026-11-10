"""Shared records for trades, prices, and league rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


def parse_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "na"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text.lower() in {"none", "null", "n/a", "na"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@dataclass
class Trade:
    bioguide_id: str
    symbol: str
    transaction_type: str
    transaction_date: date | None
    filed_date: date | None
    notification_date: date | None
    amount_min: float | None
    amount_max: float | None
    asset_name: str
    asset_type_code: str | None
    owner_code: str | None
    source_url: str | None
    chamber: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def disclosure_date(self) -> date | None:
        """Public disclosure date. Alpha Vantage calls this filed_date."""
        return self.filed_date or self.notification_date


@dataclass
class Politician:
    bioguide_id: str
    name: str
    chamber: str
    party: str
    state: str
    district: str | None
    terms: list[dict]
    years_in_service: float


@dataclass
class HoldingSlice:
    """A FIFO lot, or the part of a lot closed by one sale."""

    symbol: str
    shares: float
    cost: float
    entry_date: date
    entry_price: float
    exit_date: date | None
    exit_price: float | None
    disclosure_date: date | None


@dataclass
class MeasuredLot:
    symbol: str
    pnl: float
    weight: float
    benchmark_pnl: float
    entry_date: date
    exit_date: date
    hold_days: int


@dataclass
class WindowPerformance:
    member_return: float | None
    benchmark_return: float | None
    alpha: float | None
    weight: float
    lots: list[MeasuredLot] = field(default_factory=list)
    uncopyable: int = 0
    missing_price: int = 0


@dataclass
class MemberStats:
    their_return: float | None = None
    their_alpha: float | None = None
    their_benchmark: float | None = None
    copycat_return: float | None = None
    copycat_alpha: float | None = None
    trade_count: int = 0
    excluded_options: int = 0
    excluded_non_stock: int = 0
    excluded_unknown: int = 0
    excluded_other: int = 0
    unmatched_sells: int = 0
    uncopyable: int = 0
    avg_hold_days: float | None = None
    avg_filing_lag: float | None = None
    late_filings: int = 0
    filings: int = 0
    on_time_filings: int = 0
    tech_share: float | None = None
    top_two_share: float | None = None
    realized_return: float | None = None
    weight: float = 0.0
    curve: list[dict] = field(default_factory=list)


@dataclass
class BoardRow:
    bioguide_id: str
    name: str
    initials: str
    chamber: str
    party: str
    state: str
    district: str | None
    years_in_service: float
    stats: MemberStats
    rank: int | None = None
    previous_rank: int | None = None
    rank_change: int | None = None
    streak: int = 0
    on_fire: bool = False
    took_first: bool = False
    benched: bool = True
    badges: list[str] = field(default_factory=list)

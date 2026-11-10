"""Runtime settings. The API key is read from the environment and never logged."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return int(raw)


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw == "":
        return default
    return float(raw)


# Most-traded names on recent Congress disclosures; each call returns hundreds
# of trades across many members.
DEFAULT_DISCOVERY = "NVDA,MSFT,AAPL,AMZN,GOOGL,META,TSLA,AVGO"


@dataclass(frozen=True)
class Settings:
    api_key: str
    requests_per_minute: int
    requests_per_day: int
    price_function: str
    outputsize: str
    price_budget_share: float
    max_requests_per_run: int
    min_trades: int
    late_days: int
    db_path: Path
    site_data: Path
    metadata_refresh_days: int = 7
    # One CONGRESS_TRADES call per symbol shows which members actually trade,
    # so those are fetched first. Empty tuple turns discovery off.
    discovery_symbols: tuple[str, ...] = ()
    discovery_refresh_days: int = 30
    active_refresh_days: int = 3
    inactive_refresh_days: int = 60
    base_url: str = "https://www.alphavantage.co/query"

    @property
    def daily_unlimited(self) -> bool:
        return self.requests_per_day <= 0


def load_settings() -> Settings:
    """Load settings from the environment.

    AV_REQUESTS_PER_DAY=0 means the plan has no daily cap (Alpha Vantage premium).
    """
    data_root = Path(os.environ.get("CAPITOL_DATA_DIR", ROOT / "data"))
    site = Path(os.environ.get("CAPITOL_SITE_DATA", ROOT / "web" / "public" / "data"))
    return Settings(
        api_key=os.environ.get("ALPHAVANTAGE_API_KEY", "").strip(),
        requests_per_minute=max(1, _int("AV_REQUESTS_PER_MINUTE", 5)),
        requests_per_day=_int("AV_REQUESTS_PER_DAY", 25),
        price_function=os.environ.get("AV_PRICE_FUNCTION", "TIME_SERIES_DAILY").strip()
        or "TIME_SERIES_DAILY",
        outputsize=os.environ.get("AV_OUTPUTSIZE", "compact").strip() or "compact",
        price_budget_share=min(0.9, max(0.05, _float("AV_PRICE_BUDGET_SHARE", 0.35))),
        max_requests_per_run=max(1, _int("AV_MAX_REQUESTS_PER_RUN", 8000)),
        min_trades=max(1, _int("AV_MIN_TRADES", 3)),
        late_days=max(1, _int("AV_LATE_DAYS", 45)),
        db_path=data_root / "cache" / "capitol.sqlite",
        site_data=site,
        discovery_symbols=tuple(
            sym.strip().upper()
            for sym in os.environ.get("AV_DISCOVERY_SYMBOLS", DEFAULT_DISCOVERY).split(",")
            if sym.strip()
        ),
    )

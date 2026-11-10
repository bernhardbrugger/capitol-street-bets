from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from capitol_street_bets.db import connect, last_bar, load_price_book_rows, get_meta
from capitol_street_bets.ingest import ingest_massive_prices
from capitol_street_bets.massive import MassiveClient, _session_day

from test_ingest import _settings

NY = ZoneInfo("America/New_York")
KEY = "SECRET-MASSIVE-KEY"


def _ms(day: str) -> int:
    d = date.fromisoformat(day)
    return int(datetime(d.year, d.month, d.day, tzinfo=NY).timestamp() * 1000)


def _seed_trades(conn, symbols):
    import json

    for i, symbol in enumerate(symbols):
        payload = {
            "bioguide_id": "A000001", "symbol": symbol, "transaction_type": "BUY",
            "transaction_date": "2026-10-01", "filed_date": "2026-10-10",
            "amount_min": "1001", "amount_max": "15000", "asset_name": f"{symbol} Inc [ST]",
            "asset_type": "ST",
        }
        conn.execute(
            "INSERT INTO trades (trade_id, bioguide_id, payload_json) VALUES (?, ?, ?)",
            (f"t{i}", "A000001", json.dumps(payload)),
        )
    conn.commit()


class FakeMassive:
    def __init__(self):
        self.calls = []
        self.throttle_once = True

    def __call__(self, path, params):
        assert KEY not in path and KEY not in str(params)
        self.calls.append(path)
        if "/grouped/" in path:
            day = path.rsplit("/", 1)[1]
            if day == "2026-11-11":  # pretend holiday
                return 200, {"resultsCount": 0, "results": []}
            if self.throttle_once:
                self.throttle_once = False
                return 429, {"status": "ERROR"}
            return 200, {"results": [{"T": "SPY", "c": 600.0}, {"T": "NVDA", "c": 190.0}, {"T": "ZZZ", "c": 1.0}]}
        symbol = path.split("/")[4]
        if symbol == "GONE":
            return 200, {"resultsCount": 0}
        return 200, {"results": [{"t": _ms("2026-11-05"), "c": 100.0}, {"t": _ms("2026-11-06"), "c": 101.0}]}


def test_session_day_uses_new_york_date():
    assert _session_day(_ms("2026-11-06")) == "2026-11-06"


def test_backfill_then_grouped_catch_up(tmp_path: Path):
    settings = replace(_settings(tmp_path), massive_api_key=KEY)
    conn = connect(settings.db_path)
    _seed_trades(conn, ["NVDA", "GONE"])
    fake = FakeMassive()
    sleeps = []
    client = MassiveClient(KEY, per_minute=1000, transport=fake, sleep=sleeps.append)

    report = ingest_massive_prices(settings, conn, client, today=date(2026, 11, 10))
    assert report["backfilled"] == ["SPY", "NVDA"]
    assert report["empty"] == ["GONE"]
    # Backfill ended on 11-06 (Fri); target is Mon 11-09, one grouped call.
    assert report["sessions"] == ["2026-11-09"]
    assert last_bar(conn, "NVDA") == "2026-11-09"
    assert load_price_book_rows(conn)["NVDA"]["2026-11-09"] == 190.0
    assert 61.0 in sleeps  # 429 waited out
    assert get_meta(conn, "price_source") == "massive"
    assert KEY not in str(report)

    # Next day: no history calls, one grouped call, holiday skipped, GONE not retried.
    fake.calls.clear()
    report = ingest_massive_prices(settings, conn, client, today=date(2026, 11, 13))
    assert all("/grouped/" in path for path in fake.calls)
    assert report["sessions"] == ["2026-11-10", "2026-11-12"]


def test_alpha_vantage_skips_prices_when_massive_is_on(tmp_path: Path):
    from capitol_street_bets.ingest import budget_plan

    plan = budget_plan(25, False, 500, 0, 0.0, False)
    assert plan["prices"] == 0 and plan["members"] == 25

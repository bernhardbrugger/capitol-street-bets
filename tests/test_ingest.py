"""Ingestion against a fake Alpha Vantage: throttle, resume, and a warm cache."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from capitol_street_bets.av import AlphaVantageClient, parse_limits
from capitol_street_bets.config import Settings
from capitol_street_bets.db import connect, get_meta
from capitol_street_bets.ingest import ingest

SECRET = "SUPERSECRETKEY"


class Clock:
    def __init__(self, moment: datetime):
        self.now = moment

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        api_key=SECRET,
        requests_per_minute=30,
        requests_per_day=2,
        price_function="TIME_SERIES_DAILY",
        outputsize="compact",
        price_budget_share=0.35,
        max_requests_per_run=50,
        min_trades=3,
        late_days=45,
        db_path=tmp_path / "cache" / "capitol.sqlite",
        site_data=tmp_path / "site",
        metadata_refresh_days=7,
    )
    values.update(overrides)
    return Settings(**values)


def _person(bioguide: str, name: str) -> dict:
    return {
        "bioguide_id": bioguide,
        "display_name": name,
        "chamber": "house",
        "state": "OR",
        "district": "3",
        "party": "R",
        "terms": [
            {
                "chamber": "house",
                "state": "OR",
                "district": "3",
                "start_date": "2025-01-03",
                "end_date": "2027-01-03",
            }
        ],
    }


def _trade(bioguide: str, symbol: str = "AAPL") -> dict:
    return {
        "bioguide_id": bioguide,
        "symbol": symbol,
        "transaction_type": "BUY",
        "transaction_date": "2026-10-01",
        "filed_date": "2026-10-08",
        "notification_date": "2026-10-08",
        "amount_min": "1001.00",
        "amount_max": "15000.00",
        "asset_name": f"{symbol} Common Stock [ST]",
        "asset_type_code": "ST",
        "owner_code": "SELF",
        "chamber": "HOUSE",
    }


def _series(symbol: str) -> dict:
    return {
        "Meta Data": {"2. Symbol": symbol},
        "Time Series (Daily)": {
            "2026-11-06": {"4. close": "100.00", "5. volume": "10"},
            "2026-11-09": {"4. close": "101.00", "5. volume": "11"},
        },
    }


def _world(calls: list[dict]):
    def transport(params: dict) -> dict:
        safe = {key: value for key, value in params.items() if key != "apikey"}
        calls.append(safe)
        assert SECRET not in str(safe)
        function = params["function"]
        if function == "POLITICIAN_METADATA":
            return {"politicians": [_person("A000001", "Alex Adey"), _person("B000002", "Blair Beck")]}
        if function == "CONGRESS_TRADES":
            return {"trades": [_trade(params["bioguide_id"])]}
        if function.startswith("TIME_SERIES"):
            return _series(params["symbol"])
        raise AssertionError(function)

    return transport


def test_limit_parser_reads_the_note():
    note = (
        "Thank you for using Alpha Vantage! Our standard API call frequency is "
        "5 calls per minute and 25 calls per day."
    )
    found = parse_limits(note)
    assert found.per_minute == 5
    assert found.per_day == 25


def test_rate_limit_retries_and_stores_detected_plan(tmp_path: Path):
    calls: list[dict] = []
    state = {"hits": 0}

    def transport(params: dict) -> dict:
        calls.append(params["function"])
        assert SECRET not in str(params.get("function"))
        state["hits"] += 1
        if state["hits"] == 1:
            return {
                "Note": (
                    "Thank you for using Alpha Vantage! Our standard API call frequency "
                    "is 5 calls per minute and 25 calls per day."
                )
            }
        function = params["function"]
        if function == "POLITICIAN_METADATA":
            return {"politicians": [_person("A000001", "Alex Adey")]}
        if function == "CONGRESS_TRADES":
            return {"trades": [_trade(params["bioguide_id"])]}
        if function.startswith("TIME_SERIES"):
            return _series(params["symbol"])
        raise AssertionError(function)

    clock = Clock(datetime(2026, 11, 6, 15, tzinfo=timezone.utc))
    settings = _settings(tmp_path, requests_per_day=20, requests_per_minute=10)
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=transport, sleep=clock.sleep, clock=clock)
    report = ingest(settings, conn, client, today=clock.now.date())
    assert calls[0] == "POLITICIAN_METADATA"
    assert calls[1] == "POLITICIAN_METADATA"
    assert get_meta(conn, "detected_per_minute") == "5"
    assert get_meta(conn, "detected_per_day") == "25"
    assert report["stopped"] is None
    assert SECRET not in str(report)


def test_resume_after_daily_budget_and_skip_fresh_prices(tmp_path: Path):
    calls: list[dict] = []
    clock = Clock(datetime(2026, 11, 6, 18, tzinfo=timezone.utc))
    settings = _settings(tmp_path, requests_per_day=2)
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=_world(calls), sleep=clock.sleep, clock=clock)

    first = ingest(settings, conn, client, today=clock.now.date())
    assert [call["function"] for call in calls] == ["POLITICIAN_METADATA", "CONGRESS_TRADES"]
    assert calls[1]["bioguide_id"] == "A000001"
    assert first["members"] == ["A000001"]
    assert first["prices"] == []

    clock.now = datetime(2026, 11, 9, 18, tzinfo=timezone.utc)
    before = len(calls)
    second = ingest(settings, conn, client, today=clock.now.date())
    new_calls = calls[before:]
    assert [call["function"] for call in new_calls] == ["CONGRESS_TRADES", "TIME_SERIES_DAILY"]
    assert new_calls[0]["bioguide_id"] == "B000002"
    assert second["prices"] == ["SPY"]

    # Same day, with room left: the remaining member and the new ticker.
    # SPY already covers the latest session, so it is not requested again.
    roomy = _settings(tmp_path, requests_per_day=10)
    client.settings = roomy
    before = len(calls)
    third = ingest(roomy, conn, client, today=clock.now.date())
    third_calls = calls[before:]
    assert "SPY" not in [call.get("symbol") for call in third_calls]
    assert third["members"] == ["A000001"]
    assert third["prices"] == ["AAPL"]

    before = len(calls)
    fourth = ingest(roomy, conn, client, today=clock.now.date())
    assert calls[before:] == []
    assert fourth["members"] == []
    assert fourth["prices"] == []
    stored = conn.execute("SELECT COUNT(*) AS n FROM prices WHERE symbol = 'AAPL'").fetchone()["n"]
    assert stored == 2


def test_unchanged_member_payload_is_not_rewritten(tmp_path: Path):
    calls: list[dict] = []
    clock = Clock(datetime(2026, 11, 6, 18, tzinfo=timezone.utc))
    settings = _settings(tmp_path, requests_per_day=0, max_requests_per_run=20, price_budget_share=0.1)
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=_world(calls), sleep=clock.sleep, clock=clock)
    ingest(settings, conn, client, today=clock.now.date())
    first_count = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    clock.now += timedelta(days=3)
    ingest(settings, conn, client, today=clock.now.date())
    second_count = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
    assert first_count == second_count == 2
    unchanged = conn.execute(
        "SELECT COUNT(*) AS n FROM member_sync WHERE status = 'unchanged'"
    ).fetchone()["n"]
    assert unchanged == 2


def test_adjusted_endpoint_falls_back_when_the_plan_says_premium(tmp_path: Path):
    calls: list[str] = []

    def transport(params: dict) -> dict:
        calls.append(params["function"])
        function = params["function"]
        if function == "POLITICIAN_METADATA":
            return {"politicians": [_person("A000001", "Alex Adey")]}
        if function == "CONGRESS_TRADES":
            return {"trades": [_trade("A000001")]}
        if function == "TIME_SERIES_DAILY_ADJUSTED":
            return {"Information": "Thank you for using Alpha Vantage! This is a premium endpoint."}
        if function == "TIME_SERIES_DAILY":
            return _series(params["symbol"])
        raise AssertionError(function)

    clock = Clock(datetime(2026, 11, 6, 18, tzinfo=timezone.utc))
    settings = _settings(
        tmp_path,
        requests_per_day=0,
        max_requests_per_run=20,
        price_function="TIME_SERIES_DAILY_ADJUSTED",
    )
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=transport, sleep=clock.sleep, clock=clock)
    report = ingest(settings, conn, client, today=clock.now.date())
    assert "TIME_SERIES_DAILY_ADJUSTED" in calls
    assert "TIME_SERIES_DAILY" in calls
    assert report["prices"]
    assert get_meta(conn, "price_function") == "TIME_SERIES_DAILY"


def test_identical_trade_rows_are_kept_as_separate_transactions(tmp_path):
    from capitol_street_bets.db import connect, iter_trades
    from capitol_street_bets.ingest import _pull_member

    row = {
        "bioguide_id": "X000001", "symbol": "NVDA", "transaction_type": "BUY",
        "transaction_date": "2026-10-01", "filed_date": "2026-10-20",
        "amount_min": "1001", "amount_max": "15000", "owner_code": "SPOUSE",
        "asset_name": "NVIDIA Corp [ST]",
    }

    class FakeClient:
        def congress_trades(self, bioguide_id):
            return {"trades": [dict(row), dict(row)]}

        def clock(self):
            return datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)

    conn = connect(tmp_path / "c.sqlite")
    assert _pull_member(FakeClient(), conn, "X000001") is True
    assert len(iter_trades(conn)) == 2


def test_discovery_puts_active_traders_first(tmp_path: Path):
    from dataclasses import replace

    calls: list[dict] = []
    base = _world(calls)

    def transport(params: dict) -> dict:
        if params["function"] == "CONGRESS_TRADES" and "symbol" in params:
            calls.append({k: v for k, v in params.items() if k != "apikey"})
            # Only B trades NVDA, and often.
            return {"trades": [_trade("B000002", "NVDA") for _ in range(5)]}
        return base(params)

    clock = Clock(datetime(2026, 11, 9, 18, tzinfo=timezone.utc))
    settings = replace(_settings(tmp_path, requests_per_day=6), discovery_symbols=("NVDA",))
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=transport, sleep=clock.sleep, clock=clock)
    report = ingest(settings, conn, client, today=clock.now.date())

    order = [c.get("symbol") or c.get("bioguide_id") or c["function"] for c in calls]
    assert order[:3] == ["POLITICIAN_METADATA", "NVDA", "B000002"]
    assert report["discovery"] == ["NVDA"]
    # Discovery is a hint only: no trades are stored from the symbol pull.
    stored = {row["bioguide_id"] for row in conn.execute("SELECT DISTINCT bioguide_id FROM trades")}
    assert "B000002" in stored and len(stored) <= 2

    # Not repeated the next day.
    clock.now = datetime(2026, 11, 10, 18, tzinfo=timezone.utc)
    before = len(calls)
    ingest(settings, conn, client, today=clock.now.date())
    assert all(c.get("symbol") != "NVDA" or c["function"] != "CONGRESS_TRADES" for c in calls[before:])


def test_daily_cap_message_stops_without_retrying(tmp_path: Path):
    calls: list[str] = []

    def transport(params: dict) -> dict:
        calls.append(params["function"])
        return {"Information": "We have detected your API key as XYZ and our standard API rate limit is 25 requests per day. Please subscribe to any of the premium plans."}

    clock = Clock(datetime(2026, 11, 6, 15, tzinfo=timezone.utc))
    settings = _settings(tmp_path, requests_per_day=25)
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=transport, sleep=clock.sleep, clock=clock)
    report = ingest(settings, conn, client, today=clock.now.date())
    assert len(calls) == 1
    assert "daily limit" in report["stopped"]


def test_calls_are_spaced_and_burst_note_is_not_a_daily_stop(tmp_path: Path):
    calls: list[str] = []
    state = {"n": 0}

    def transport(params: dict) -> dict:
        calls.append(params["function"])
        state["n"] += 1
        if state["n"] == 2:
            return {"Information": "Thank you for using Alpha Vantage! Please consider spreading out your free API requests more sparingly (1 request per second). You may subscribe to any of the premium plans to lift the free key rate limit (25 requests per day)."}
        if params["function"] == "POLITICIAN_METADATA":
            return {"politicians": [_person("A000001", "Alex Adey"), _person("B000002", "Bea Bay")]}
        if params["function"].startswith("TIME_SERIES"):
            return _series(params["symbol"])
        return {"trades": [_trade(params["bioguide_id"])]}

    clock = Clock(datetime(2026, 11, 6, 15, tzinfo=timezone.utc))
    settings = _settings(tmp_path, requests_per_day=25, requests_per_minute=5)
    conn = connect(settings.db_path)
    client = AlphaVantageClient(settings, conn, transport=transport, sleep=clock.sleep, clock=clock)
    report = ingest(settings, conn, client, today=clock.now.date())
    assert report["stopped"] is None or "daily limit" not in report["stopped"]
    assert len(report["members"]) >= 1
    stamps = sorted(r[0] for r in conn.execute("SELECT ts FROM request_log"))
    gaps = [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() for a, b in zip(stamps, stamps[1:])]
    assert gaps and min(gaps) >= 11.9

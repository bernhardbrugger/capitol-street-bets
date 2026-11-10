"""Hand-calculated holding periods. Expected numbers are literals, not the engine."""

from datetime import date

import pytest

from capitol_street_bets.models import Trade
from capitol_street_bets.prices import PriceBook
from capitol_street_bets.returns import midpoint, score_member

AS_OF = date(2024, 3, 1)


def _book() -> PriceBook:
    aapl = {
        date(2024, 1, 2): 100.0,
        date(2024, 1, 4): 100.0,
        date(2024, 1, 5): 125.0,
        date(2024, 1, 10): 125.0,
        date(2024, 1, 16): 110.0,
        date(2024, 1, 20): 110.0,
        date(2024, 2, 1): 150.0,
        date(2024, 3, 1): 80.0,
    }
    spy = {
        date(2024, 1, 2): 100.0,
        date(2024, 1, 4): 100.0,
        date(2024, 1, 5): 100.0,
        date(2024, 1, 10): 100.0,
        date(2024, 1, 16): 100.0,
        date(2024, 1, 20): 105.0,
        date(2024, 2, 1): 110.0,
        date(2024, 3, 1): 120.0,
    }
    return PriceBook({"AAPL": aapl, "SPY": spy, "ZZZZ": {}})


def _trade(**kwargs) -> Trade:
    base = dict(
        bioguide_id="T000001",
        symbol="AAPL",
        transaction_type="BUY",
        transaction_date=date(2024, 1, 2),
        filed_date=date(2024, 1, 5),
        notification_date=None,
        amount_min=10000.0,
        amount_max=10000.0,
        asset_name="Apple Inc. Common Stock [ST]",
        asset_type_code="ST",
        owner_code="SELF",
        source_url="https://disclosures-clerk.house.gov/example",
    )
    base.update(kwargs)
    return Trade(**base)


def test_midpoint_of_a_disclosed_range():
    # $1,001 – $15,000 is the smallest STOCK Act bucket.
    dollars, how = midpoint(1001.0, 15000.0)
    assert dollars == 8000.5
    assert how == "midpoint"
    floor, flagged = midpoint(50000001.0, None)
    assert floor == 50000001.0
    assert flagged == "open_ended_floor"


def test_fifo_partial_sale_mark_to_market_and_spy():
    trades = [
        _trade(transaction_date=date(2024, 1, 2), filed_date=date(2024, 1, 5), amount_min=10000, amount_max=10000),
        _trade(
            transaction_date=date(2024, 1, 16),
            filed_date=date(2024, 1, 20),
            amount_min=11000,
            amount_max=11000,
        ),
        _trade(
            transaction_type="SELL",
            transaction_date=date(2024, 2, 1),
            filed_date=date(2024, 2, 2),
            amount_min=7500,
            amount_max=7500,
        ),
    ]
    stats = score_member(trades, _book(), "all", AS_OF)
    # Buy 100 shares at 100, buy 100 at 110, sell 50 of the first lot at 150.
    # Closed: 50 * (150 - 100) = 2500 on 5000 of weight.
    # Open remainder: 50 * (80 - 100) = -1000 on 5000.
    # Second lot: 100 * (80 - 110) = -3000 on 11000.
    # P&L -1500 / weight 21000. SPY P&L 3700 / 21000.
    assert stats.their_return == pytest.approx(-1500 / 21000)
    assert stats.their_benchmark == pytest.approx(3700 / 21000)
    assert stats.their_alpha == pytest.approx(-5200 / 21000)
    assert stats.trade_count == 3
    assert stats.avg_hold_days == pytest.approx((30 + 59 + 45) / 3)
    # Lags: 3, 4, and 1 day. None of them cross 45.
    assert stats.avg_filing_lag == pytest.approx((3 + 4 + 1) / 3)
    assert stats.late_filings == 0
    # Sale of the first lot was a gain: 50 * 50 / 5000 = 0.5, blended with
    # nothing else closed. Realized is that closed lot only.
    assert stats.realized_return == pytest.approx(0.5)


def test_copycat_uses_disclosure_prices():
    trades = [
        _trade(transaction_date=date(2024, 1, 2), filed_date=date(2024, 1, 5), amount_min=10000, amount_max=10000),
        _trade(
            transaction_date=date(2024, 1, 16),
            filed_date=date(2024, 1, 20),
            amount_min=11000,
            amount_max=11000,
        ),
        _trade(
            transaction_type="SELL",
            transaction_date=date(2024, 2, 1),
            filed_date=date(2024, 2, 2),
            amount_min=7500,
            amount_max=7500,
        ),
    ]
    stats = score_member(trades, _book(), "all", AS_OF)
    # Same dollars deployed at the disclosure close (125, then 110).
    # Copycat P&L -3800 on the same 21000 of weight at each measurement start.
    # Benchmark P&L = 500 + 1000 + 11000/7.
    bench = 500 + 1000 + (11000 / 7)
    assert stats.copycat_return == pytest.approx(-3800 / 21000)
    assert stats.copycat_alpha == pytest.approx((-3800 / 21000) - (bench / 21000))


def test_window_clips_to_the_same_span_as_spy():
    trades = [
        _trade(transaction_date=date(2024, 1, 2), filed_date=date(2024, 1, 5), amount_min=10000, amount_max=10000),
        _trade(
            transaction_date=date(2024, 1, 16),
            filed_date=date(2024, 1, 20),
            amount_min=11000,
            amount_max=11000,
        ),
        _trade(
            transaction_type="SELL",
            transaction_date=date(2024, 2, 1),
            filed_date=date(2024, 2, 2),
            amount_min=7500,
            amount_max=7500,
        ),
    ]
    # Force the 30-day-style clip by asking for a custom window via "ytd"
    # after shifting as_of, and also call the measurer through a window whose
    # start is 2024-02-01. "ytd" of 2024-03-01 starts Jan 1, so use score on
    # a book and the all-window helper indirectly: build a one-day-later as_of
    # is not Feb 1. Call measure through score_member is window-based.
    # 2024-03-01 minus nothing equals ytd from Jan 1, which includes the sale.
    # Use the public window named by passing as_of and relying on 30d? 30d
    # from Mar 1 starts Jan 31, and the sale is Feb 1, so the open lots clip
    # to Jan 31, not Feb 1. Assert the Feb 1 clip through measure() directly.
    from capitol_street_bets.returns import build_slices, measure

    slices, _counts = build_slices(trades, _book())
    perf = measure(slices, _book(), date(2024, 2, 1), date(2024, 3, 1), "their")
    assert perf.member_return == pytest.approx(-10500 / 22500)
    assert perf.benchmark_return == pytest.approx(1 / 11)
    assert perf.alpha == pytest.approx((-10500 / 22500) - (1 / 11))


def test_sale_before_disclosure_is_not_copyable():
    trades = [
        _trade(
            transaction_date=date(2024, 1, 2),
            filed_date=date(2024, 1, 10),
            amount_min=10000,
            amount_max=10000,
        ),
        _trade(
            transaction_type="SALE",
            transaction_date=date(2024, 1, 4),
            filed_date=date(2024, 1, 10),
            amount_min=10000,
            amount_max=10000,
        ),
    ]
    stats = score_member(trades, _book(), "all", AS_OF)
    assert stats.their_return is not None
    assert stats.copycat_return is None
    assert stats.uncopyable >= 1


def test_options_unknown_tickers_and_unmatched_sells_are_counted():
    trades = [
        _trade(
            symbol="AAPL240119C00100000",
            asset_type_code="OP",
            asset_name="AAPL call option",
            transaction_date=date(2024, 1, 2),
        ),
        _trade(symbol="ZZZZ", asset_name="Mystery Motors Common Stock [ST]", transaction_date=date(2024, 1, 2)),
        _trade(
            transaction_type="SELL",
            transaction_date=date(2024, 1, 16),
            filed_date=date(2024, 1, 20),
            amount_min=5000,
            amount_max=5000,
        ),
    ]
    stats = score_member(trades, _book(), "all", AS_OF)
    # The unmatched AAPL sale is a priced equity trade, so it counts toward
    # the activity gate even though it cannot open a return.
    assert stats.trade_count == 1
    assert stats.excluded_options == 1
    assert stats.excluded_unknown >= 1
    assert stats.unmatched_sells == 1
    assert stats.their_return is None


def test_late_filing_flag_uses_45_days():
    on_time = _trade(transaction_date=date(2024, 1, 2), filed_date=date(2024, 2, 16))
    late = _trade(transaction_date=date(2024, 1, 2), filed_date=date(2024, 2, 17))
    # 2024-01-02 + 45 days = 2024-02-16. The next day is late.
    assert (date(2024, 2, 16) - date(2024, 1, 2)).days == 45
    assert (date(2024, 2, 17) - date(2024, 1, 2)).days == 46
    early_stats = score_member([on_time], _book(), "all", AS_OF)
    late_stats = score_member([late], _book(), "all", AS_OF)
    assert early_stats.late_filings == 0
    assert late_stats.late_filings == 1


def test_source_url_is_kept_when_the_feed_has_one():
    from capitol_street_bets.returns import trade_from_api

    trade = trade_from_api(
        {
            "bioguide_id": "T000001",
            "symbol": "AAPL",
            "transaction_type": "BUY",
            "transaction_date": "2024-01-02",
            "filed_date": "2024-01-05",
            "amount_min": "1001",
            "amount_max": "15000",
            "asset_type_code": "ST",
            "asset_name": "Apple [ST]",
            "source_url": "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/example.pdf",
        }
    )
    assert trade.source_url.endswith("example.pdf")
    assert trade.amount_min == 1001
    missing = trade_from_api(
        {
            "bioguide_id": "T000001",
            "symbol": "AAPL",
            "transaction_type": "BUY",
            "transaction_date": "2024-01-02",
            "asset_type_code": "ST",
            "asset_name": "Apple [ST]",
        }
    )
    assert missing.source_url is None

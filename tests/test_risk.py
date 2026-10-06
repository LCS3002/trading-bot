"""Position sizing is where a bug costs real money, and all of it is pure arithmetic —
so it should be the best-tested code in the repo."""

import pytest

from risk import risk_instance

calc = risk_instance.calculate_position_size


# ── Which cap binds ───────────────────────────────────────────────────────────


def test_risk_budget_binds_when_the_stop_is_wide():
    # $10,000 × 2% = $200 of risk, over a $2.00 stop = 100 shares.
    # Notional cap would allow 10,000 × 25% / $10 = 250, so risk is the tighter one.
    assert calc(10_000, 0.02, current_price=10.0, stop_loss_distance=2.0) == 100


def test_notional_cap_binds_when_the_stop_is_tight():
    """A tight intraday ATR makes the risk budget ask for an absurd position — this
    cap is the only thing standing between a 10c stop and 2,000 shares."""
    # risk budget: $200 / $0.10 = 2,000 shares. Notional cap: 25% of $10k / $10 = 250.
    assert calc(10_000, 0.02, current_price=10.0, stop_loss_distance=0.10) == 250


def test_buying_power_binds_when_it_is_the_smallest():
    # risk budget 100, notional cap 250, buying power only $300 / $10 = 30
    assert (
        calc(10_000, 0.02, current_price=10.0, stop_loss_distance=2.0, buying_power=300.0)
        == 30
    )


def test_max_position_pct_is_honoured():
    assert calc(
        10_000, 0.02, current_price=10.0, stop_loss_distance=0.10, max_position_pct=0.10
    ) == 100


# ── Refusals ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("price", [0.0, -5.0])
def test_non_positive_price_trades_nothing(price):
    assert calc(10_000, 0.02, current_price=price, stop_loss_distance=1.0) == 0


@pytest.mark.parametrize("stop", [0.0, -1.0])
def test_non_positive_stop_distance_trades_nothing(stop):
    """A zero stop distance would divide by zero, and a stop at the entry is not a
    stop — either way the answer is 'do not trade'."""
    assert calc(10_000, 0.02, current_price=10.0, stop_loss_distance=stop) == 0


def test_result_is_never_negative():
    assert calc(10.0, 0.02, current_price=1_000.0, stop_loss_distance=5.0) >= 0


def test_an_account_too_small_for_one_share_trades_nothing():
    assert calc(50.0, 0.02, current_price=500.0, stop_loss_distance=1.0) == 0


def test_returns_a_whole_number_of_shares():
    shares = calc(9_999, 0.0237, current_price=7.31, stop_loss_distance=1.37)
    assert isinstance(shares, int)


# ── ATR stop ──────────────────────────────────────────────────────────────────


def test_atr_stop_is_the_atr_times_the_multiplier(bars):
    closes = [100.0] * 40
    df = bars(closes, highs=[101.0] * 40, lows=[99.0] * 40)  # true range flat at 2.0

    assert risk_instance.calculate_atr_stop(df, atr_multiplier=2.0) == pytest.approx(4.0)
    assert risk_instance.calculate_atr_stop(df, atr_multiplier=1.5) == pytest.approx(3.0)


def test_atr_stop_is_none_when_there_are_too_few_bars(bars):
    assert risk_instance.calculate_atr_stop(bars([100.0] * 10)) is None


def test_atr_stop_is_none_when_the_market_has_no_range(bars):
    """Zero ATR would produce a zero stop distance, which sizing then refuses — but
    catch it here so the caller skips the trade for a legible reason."""
    closes = [100.0] * 40
    df = bars(closes, highs=closes, lows=closes)

    assert risk_instance.calculate_atr_stop(df) is None


def test_atr_stop_is_none_on_empty_input():
    import pandas as pd

    assert risk_instance.calculate_atr_stop(pd.DataFrame()) is None


def test_dynamic_position_composes_sizing_and_the_stop(bars):
    closes = [100.0] * 40
    df = bars(closes, highs=[101.0] * 40, lows=[99.0] * 40)  # ATR 2.0 → stop 4.0

    shares, stop_distance = risk_instance.calculate_dynamic_position(
        account_balance=100_000,
        risk_per_trade=0.02,
        ticker_data=df,
        current_price=100.0,
        atr_multiplier=2.0,
    )

    assert stop_distance == pytest.approx(4.0)
    # risk budget: $2,000 / $4 = 500; notional cap: 25% of $100k / $100 = 250
    assert shares == 250


def test_dynamic_position_returns_nones_when_atr_is_unavailable(bars):
    shares, stop = risk_instance.calculate_dynamic_position(
        account_balance=100_000,
        risk_per_trade=0.02,
        ticker_data=bars([100.0] * 5),
        current_price=100.0,
    )

    assert shares is None and stop is None

"""Indicator correctness against values that can be derived by hand.

These are deliberately exact rather than approximate: the whole reason for writing the
indicators out instead of importing pandas-ta is that the arithmetic is checkable.
"""

import numpy as np
import pytest

from indicators import _ema, _rma, indicators_instance


# ── Smoothing primitives ──────────────────────────────────────────────────────


def test_rma_seeds_with_simple_mean_then_smooths():
    values = np.array([1.0, 2.0, 3.0, 4.0, 10.0])
    out = _rma(values, length=4)

    assert np.isnan(out[:3]).all(), "first length-1 values have no seed yet"
    assert out[3] == pytest.approx(2.5)          # mean(1,2,3,4)
    assert out[4] == pytest.approx((2.5 * 3 + 10.0) / 4)


def test_rma_first_offset_skips_leading_gap():
    # index 0 is not a real observation (as with diff()'s leading NaN)
    values = np.array([np.nan, 2.0, 4.0, 6.0])
    out = _rma(values, length=3, first=1)

    assert np.isnan(out[:2]).all()
    assert out[3] == pytest.approx(4.0)          # mean(2,4,6)


def test_rma_returns_all_nan_when_too_short():
    assert np.isnan(_rma(np.array([1.0, 2.0]), length=5)).all()


def test_ema_uses_alpha_two_over_length_plus_one():
    values = np.array([10.0, 20.0, 30.0])
    out = _ema(values, length=2)

    alpha = 2.0 / 3.0
    assert out[1] == pytest.approx(15.0)         # mean(10,20)
    assert out[2] == pytest.approx(30.0 * alpha + 15.0 * (1 - alpha))


# ── RSI ───────────────────────────────────────────────────────────────────────


def test_rsi_is_100_for_an_unbroken_rise(bars):
    df = bars([float(i) for i in range(1, 40)])
    rsi = indicators_instance.get_rsi(df)["RSI"]

    # every delta is a gain, so average loss is zero
    assert rsi.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_0_for_an_unbroken_fall(bars):
    df = bars([float(i) for i in range(40, 1, -1)])
    rsi = indicators_instance.get_rsi(df)["RSI"]

    assert rsi.iloc[-1] == pytest.approx(0.0)


def test_rsi_is_nan_for_a_flat_series(bars):
    """Zero gain and zero loss is genuinely undefined, and must not read as 100 —
    strategy.py turns NaN into HOLD, so a motionless market cannot trade."""
    df = bars([50.0] * 40)
    assert np.isnan(indicators_instance.get_rsi(df)["RSI"].iloc[-1])


def test_rsi_first_valid_value_lands_at_index_length(bars):
    df = bars([float(i) for i in range(1, 40)])
    rsi = indicators_instance.get_rsi(df, length=14)["RSI"]

    assert rsi.iloc[:14].isna().all(), "needs 14 deltas, so 15 closes"
    assert not np.isnan(rsi.iloc[14])


def test_rsi_stays_within_bounds_on_noisy_data(bars):
    rng = np.random.default_rng(0)
    closes = (100 + np.cumsum(rng.normal(0, 1, 300))).tolist()
    rsi = indicators_instance.get_rsi(bars(closes))["RSI"].dropna()

    assert len(rsi) > 250
    assert rsi.between(0, 100).all()


# ── Warmup behaviour (NaN, never an exception) ────────────────────────────────


@pytest.mark.parametrize(
    "method, bar_count, columns",
    [
        ("get_rsi", 5, ["RSI"]),
        ("get_ema", 5, ["EMA"]),
        ("get_macd", 5, ["MACD", "Signal"]),
        ("get_atr", 5, ["ATR"]),
    ],
)
def test_short_series_returns_all_nan_frame(bars, method, bar_count, columns):
    df = bars([100.0 + i for i in range(bar_count)])
    out = getattr(indicators_instance, method)(df)

    assert list(out.columns) == columns
    assert len(out) == bar_count
    assert out.isna().all().all()
    assert out.index.equals(df.index)


def test_indicators_never_mutate_their_input(bars):
    df = bars([100.0 + i for i in range(60)])
    before = df.copy(deep=True)

    indicators_instance.get_rsi(df)
    indicators_instance.get_ema(df)
    indicators_instance.get_macd(df)
    indicators_instance.get_atr(df)

    assert df.equals(before)


# ── MACD ──────────────────────────────────────────────────────────────────────


def test_macd_is_fast_ema_minus_slow_ema(bars):
    closes = [100.0 + i * 0.5 for i in range(60)]
    df = bars(closes)

    macd = indicators_instance.get_macd(df)
    fast = indicators_instance.get_ema(df, length=12)["EMA"]
    slow = indicators_instance.get_ema(df, length=26)["EMA"]

    assert macd["MACD"].iloc[-1] == pytest.approx(fast.iloc[-1] - slow.iloc[-1])


def test_macd_signal_is_valid_only_after_its_own_warmup(bars):
    df = bars([100.0 + i * 0.5 for i in range(60)])
    out = indicators_instance.get_macd(df, fast=12, slow=26, signal=9)

    # MACD valid from index 25; signal needs 9 more
    assert np.isnan(out["Signal"].iloc[32])
    assert not np.isnan(out["Signal"].iloc[33])


def test_macd_positive_in_an_uptrend_negative_in_a_downtrend(bars):
    up = indicators_instance.get_macd(bars([100.0 + i for i in range(60)]))
    down = indicators_instance.get_macd(bars([100.0 - i for i in range(60)]))

    assert up["MACD"].iloc[-1] > 0
    assert down["MACD"].iloc[-1] < 0


# ── ATR ───────────────────────────────────────────────────────────────────────


def test_atr_of_a_constant_range_equals_that_range(bars):
    closes = [100.0] * 40
    df = bars(closes, highs=[101.0] * 40, lows=[99.0] * 40)
    atr = indicators_instance.get_atr(df)["ATR"]

    # true range is a flat 2.0 every bar, so any average of it is 2.0
    assert atr.iloc[-1] == pytest.approx(2.0)


def test_atr_accounts_for_gaps_beyond_the_bar_range(bars):
    """True range must include |high - prev_close|, otherwise an overnight gap
    looks calm and the stop distance comes out far too tight."""
    closes = [100.0] * 20 + [130.0] * 20
    df = bars(closes, highs=[c + 0.5 for c in closes], lows=[c - 0.5 for c in closes])
    atr = indicators_instance.get_atr(df)["ATR"]

    assert atr.iloc[-1] > 1.0, "a 30-point gap should widen ATR well beyond the 1.0 bar range"


def test_rsi_matches_an_independent_wilder_implementation(bars):
    """Cross-validation against a separately written textbook implementation.

    Replacing pandas-ta means the arithmetic is now this repo's responsibility, so the
    canonical definition gets checked directly rather than taken on trust. Written
    deliberately differently below — explicit loop, SMA seed, no shared helpers — so a
    mistake in `_rma` cannot hide by being made twice.

    Note this is Wilder's / TA-Lib's seeding. Some libraries (`ta`, for one) seed the
    smoothing from the first observation instead; that difference decays geometrically
    and is ~1e-11 by 250 bars, but it makes early values disagree.
    """
    rng = np.random.default_rng(42)
    closes = (100 + np.cumsum(rng.normal(0, 1.0, 400))).tolist()
    length = 14

    deltas = np.diff(np.asarray(closes))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    expected = np.full(len(closes), np.nan)
    avg_gain = gains[:length].mean()
    avg_loss = losses[:length].mean()
    expected[length] = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss else 100.0
    for i in range(length, len(deltas)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
        expected[i + 1] = (
            100.0 - 100.0 / (1.0 + avg_gain / avg_loss) if avg_loss else 100.0
        )

    actual = indicators_instance.get_rsi(bars(closes), length=length)["RSI"].to_numpy()

    valid = ~np.isnan(expected)
    assert valid.sum() > 380
    np.testing.assert_allclose(actual[valid], expected[valid], rtol=0, atol=1e-12)
    assert np.isnan(actual[:length]).all(), "first valid RSI must land at index length"


def test_atr_is_positive_and_finite_on_noisy_data(bars):
    rng = np.random.default_rng(7)
    closes = (100 + np.cumsum(rng.normal(0, 1, 200))).tolist()
    highs = [c + abs(rng.normal(0, 0.5)) for c in closes]
    lows = [c - abs(rng.normal(0, 0.5)) for c in closes]

    atr = indicators_instance.get_atr(bars(closes, highs, lows))["ATR"].dropna()
    assert len(atr) > 180
    assert (atr > 0).all()
    assert np.isfinite(atr).all()

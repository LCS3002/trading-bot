"""Signal rules, driven by exact indicator values rather than price series engineered to
produce them. Several of these are regression tests for rules that were unreachable."""

import pandas as pd
import pytest

import strategy as strategy_mod

NAN = float("nan")


@pytest.fixture
def signal(monkeypatch, bars):
    """Evaluate the decision rules with the indicators pinned to chosen values."""

    def _run(*, rsi, macd, signal_line, ema, close, **toggles):
        df = bars([close] * 60)
        idx = df.index

        def frame(**cols):
            return pd.DataFrame({k: [v] * len(idx) for k, v in cols.items()}, index=idx)

        monkeypatch.setattr(
            strategy_mod.indicators_instance, "get_rsi", lambda d, **k: frame(RSI=rsi)
        )
        monkeypatch.setattr(
            strategy_mod.indicators_instance, "get_ema", lambda d, **k: frame(EMA=ema)
        )
        monkeypatch.setattr(
            strategy_mod.indicators_instance,
            "get_macd",
            lambda d, **k: frame(MACD=macd, Signal=signal_line),
        )
        return strategy_mod.strategy_instance._evaluate(df, **toggles)["Decision"]

    return _run


MACD_ONLY = {"use_macd": True, "use_rsi": False, "use_ema_filter": True}
RSI_ONLY = {"use_macd": False, "use_rsi": True, "use_ema_filter": True}
BOTH = {"use_macd": True, "use_rsi": True, "use_ema_filter": True}


# ── MACD with the EMA trend filter (the default mode) ─────────────────────────


def test_bullish_macd_in_an_uptrend_buys(signal):
    assert signal(rsi=50, macd=1.0, signal_line=0.0, ema=99.0, close=100.0, **MACD_ONLY) == "BUY"


def test_bearish_macd_in_a_downtrend_sells(signal):
    assert signal(rsi=50, macd=-1.0, signal_line=0.0, ema=101.0, close=100.0, **MACD_ONLY) == "SELL"


def test_bullish_macd_against_the_trend_holds(signal):
    assert signal(rsi=50, macd=1.0, signal_line=0.0, ema=101.0, close=100.0, **MACD_ONLY) == "HOLD"


def test_bearish_macd_against_the_trend_holds(signal):
    assert signal(rsi=50, macd=-1.0, signal_line=0.0, ema=99.0, close=100.0, **MACD_ONLY) == "HOLD"


# ── Regression: the EMA filter made the bot silently long-only when disabled ──


def test_disabling_the_ema_filter_still_permits_sell(signal):
    """A single `above_ema` flag was set True when the filter was off, so the SELL
    branch's `not above_ema` was permanently False. Disabling the trend filter turned
    the bot long-only without saying so."""
    assert (
        signal(
            rsi=50, macd=-1.0, signal_line=0.0, ema=100.0, close=100.0,
            use_macd=True, use_rsi=False, use_ema_filter=False,
        )
        == "SELL"
    )


def test_disabling_the_ema_filter_still_permits_buy(signal):
    assert (
        signal(
            rsi=50, macd=1.0, signal_line=0.0, ema=100.0, close=100.0,
            use_macd=True, use_rsi=False, use_ema_filter=False,
        )
        == "BUY"
    )


# ── RSI alone: mean reversion, deliberately unfiltered by trend ───────────────


def test_oversold_buys_even_below_the_ema(signal):
    """Regression: requiring close > EMA(20) alongside RSI < 30 demanded an oversold
    reading inside an uptrend — contradictory by construction, so this branch
    effectively never fired."""
    assert signal(rsi=25.0, macd=0.0, signal_line=0.0, ema=110.0, close=100.0, **RSI_ONLY) == "BUY"


def test_overbought_sells_even_above_the_ema(signal):
    assert signal(rsi=75.0, macd=0.0, signal_line=0.0, ema=90.0, close=100.0, **RSI_ONLY) == "SELL"


def test_mid_range_rsi_holds(signal):
    assert signal(rsi=50.0, macd=0.0, signal_line=0.0, ema=100.0, close=100.0, **RSI_ONLY) == "HOLD"


@pytest.mark.parametrize("rsi", [30.0, 70.0])
def test_rsi_exactly_on_a_threshold_holds(signal, rsi):
    assert signal(rsi=rsi, macd=0.0, signal_line=0.0, ema=100.0, close=100.0, **RSI_ONLY) == "HOLD"


# ── MACD + RSI: RSI vetoes, it does not have to agree ────────────────────────


def test_macd_leads_and_neutral_rsi_does_not_block(signal):
    """Regression: the combined mode required RSI < 30 *and* a bullish crossover *and*
    an uptrend simultaneously, which is close to unsatisfiable."""
    assert signal(rsi=50.0, macd=1.0, signal_line=0.0, ema=99.0, close=100.0, **BOTH) == "BUY"


def test_overbought_rsi_vetoes_a_buy(signal):
    assert signal(rsi=80.0, macd=1.0, signal_line=0.0, ema=99.0, close=100.0, **BOTH) == "HOLD"


def test_oversold_rsi_blocks_selling_into_a_washout(signal):
    assert signal(rsi=20.0, macd=-1.0, signal_line=0.0, ema=101.0, close=100.0, **BOTH) == "HOLD"


def test_macd_bearish_with_neutral_rsi_sells(signal):
    assert signal(rsi=50.0, macd=-1.0, signal_line=0.0, ema=101.0, close=100.0, **BOTH) == "SELL"


def test_nan_rsi_does_not_veto_in_combined_mode(signal):
    """An unavailable RSI should not silently block every trade."""
    assert signal(rsi=NAN, macd=1.0, signal_line=0.0, ema=99.0, close=100.0, **BOTH) == "BUY"


# ── NaN indicators mean HOLD, never a crash ──────────────────────────────────


@pytest.mark.parametrize(
    "macd, signal_line, ema",
    [(NAN, 0.0, 99.0), (1.0, NAN, 99.0), (1.0, 0.0, NAN)],
)
def test_nan_in_a_required_indicator_holds(signal, macd, signal_line, ema):
    assert signal(rsi=50.0, macd=macd, signal_line=signal_line, ema=ema, close=100.0, **MACD_ONLY) == "HOLD"


def test_empty_frame_holds():
    out = strategy_mod.strategy_instance.evaluate_streaming(pd.DataFrame())
    assert out["Decision"] == "HOLD"


def test_none_input_holds():
    assert strategy_mod.strategy_instance.evaluate_streaming(None)["Decision"] == "HOLD"


def test_hold_result_carries_no_shared_mutable_state():
    """`_HOLD` is a module-level dict; callers must never be handed the original."""
    a = strategy_mod.strategy_instance.evaluate_streaming(pd.DataFrame())
    a["Decision"] = "BUY"
    b = strategy_mod.strategy_instance.evaluate_streaming(pd.DataFrame())
    assert b["Decision"] == "HOLD"

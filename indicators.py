"""
Technical indicator calculations — RSI, EMA, MACD and ATR.

Implemented directly on pandas/numpy rather than via pandas-ta. That library pulls in
numba and llvmlite, which pinned the project to Python 3.12-3.13 only; these four
formulas are short and standard, so the dependency bought a narrow interpreter window
for very little. Written out, they are also exactly verifiable against a hand-computed
series, which is what the test suite does.

All smoothing follows Wilder / TA-Lib conventions:
  · RSI and ATR use Wilder's recursive average (RMA), seeded with a simple mean
  · EMA uses alpha = 2/(length+1), also seeded with a simple mean
  · A seeded average means the first `length` rows are NaN rather than a ramp-up
    from the first observation, so early values are never quietly wrong

All methods return a new DataFrame and never mutate the input. A series shorter than
the indicator's period yields an all-NaN frame of the right shape — strategy.py already
treats NaN as HOLD, so warmup needs no special handling anywhere else.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _nan_frame(columns: list[str], index) -> pd.DataFrame:
    return pd.DataFrame({col: float("nan") for col in columns}, index=index)


def _rma(values: np.ndarray, length: int, first: int = 0) -> np.ndarray:
    """Wilder's recursive average.

    Seeded at index `first + length - 1` with the mean of values[first:first+length],
    then smoothed as (prev*(n-1) + x) / n. `first` skips leading values that are not
    real observations — the NaN that `diff()` puts at index 0, for instance.
    """
    out = np.full(values.shape, np.nan, dtype=float)
    end = first + length
    if values.size < end:
        return out

    prev = float(np.mean(values[first:end]))
    out[end - 1] = prev
    for i in range(end, values.size):
        prev = (prev * (length - 1) + values[i]) / length
        out[i] = prev
    return out


def _ema(values: np.ndarray, length: int, first: int = 0) -> np.ndarray:
    """Exponential moving average, alpha = 2/(length+1), seeded with a simple mean."""
    out = np.full(values.shape, np.nan, dtype=float)
    end = first + length
    if values.size < end:
        return out

    alpha = 2.0 / (length + 1.0)
    prev = float(np.mean(values[first:end]))
    out[end - 1] = prev
    for i in range(end, values.size):
        prev = values[i] * alpha + prev * (1.0 - alpha)
        out[i] = prev
    return out


class Indicators:
    def get_rsi(self, df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=float)
        if close.size < length + 1:
            logger.warning("RSI unavailable — %d bars, need %d", len(df), length + 1)
            return _nan_frame(["RSI"], df.index)

        delta = np.diff(close, prepend=np.nan)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)
        gain[0] = loss[0] = np.nan  # index 0 has no prior close

        # first=1 skips that gap, so the first RSI lands at index `length`
        avg_gain = _rma(gain, length, first=1)
        avg_loss = _rma(loss, length, first=1)

        with np.errstate(divide="ignore", invalid="ignore"):
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # An unbroken run of gains divides by zero; RSI is 100 there, not undefined.
        # A *flat* series has zero gain and zero loss, which stays NaN on purpose —
        # RSI genuinely is undefined, and strategy.py reads NaN as HOLD, so a
        # motionless market cannot produce a trade.
        rsi = np.where((avg_loss == 0) & (avg_gain > 0), 100.0, rsi)

        return pd.DataFrame({"RSI": rsi}, index=df.index)

    def get_ema(self, df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=float)
        if close.size < length:
            logger.warning("EMA unavailable — %d bars, need %d", len(df), length)
            return _nan_frame(["EMA"], df.index)
        return pd.DataFrame({"EMA": _ema(close, length)}, index=df.index)

    def get_macd(
        self, df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=float)
        needed = slow + signal - 1
        if close.size < needed:
            logger.warning("MACD unavailable — %d bars, need %d", len(df), needed)
            return _nan_frame(["MACD", "Signal"], df.index)

        macd = _ema(close, fast) - _ema(close, slow)
        # The signal line is an EMA of the MACD line, which only becomes valid at
        # index slow-1 — seed it from there, not from the leading NaNs.
        signal_line = _ema(macd, signal, first=slow - 1)

        return pd.DataFrame({"MACD": macd, "Signal": signal_line}, index=df.index)

    def get_atr(self, df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
        """Average true range — Wilder's RMA of the true range."""
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        if close.size < length + 1:
            logger.warning("ATR unavailable — %d bars, need %d", len(df), length + 1)
            return _nan_frame(["ATR"], df.index)

        prev_close = np.roll(close, 1)
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
        )
        tr[0] = np.nan  # no prior close, so no true range

        return pd.DataFrame({"ATR": _rma(tr, length, first=1)}, index=df.index)


indicators_instance = Indicators()

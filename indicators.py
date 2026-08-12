"""
Technical indicator calculations via pandas-ta.
All methods return a new DataFrame and never mutate the input.

pandas-ta returns None when the series is shorter than the indicator's period, so
each getter falls back to an all-NaN frame — strategy.py already treats NaN as HOLD.
"""

import logging

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


def _nan_frame(columns: list[str], index) -> pd.DataFrame:
    return pd.DataFrame({col: float("nan") for col in columns}, index=index)


class Indicators:
    def get_rsi(self, df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
        result = ta.rsi(df["close"], length=length)
        if result is None:
            logger.warning("RSI unavailable — %d bars, need %d", len(df), length + 1)
            return _nan_frame(["RSI"], df.index)
        return pd.DataFrame({"RSI": result}, index=df.index)

    def get_ema(self, df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
        result = ta.ema(df["close"], length=length)
        if result is None:
            logger.warning("EMA unavailable — %d bars, need %d", len(df), length)
            return _nan_frame(["EMA"], df.index)
        return pd.DataFrame({"EMA": result}, index=df.index)

    def get_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        result = ta.macd(df["close"])
        if result is None or "MACD_12_26_9" not in result:
            logger.warning("MACD unavailable — %d bars, need 35", len(df))
            return _nan_frame(["MACD", "Signal"], df.index)
        return result[["MACD_12_26_9", "MACDs_12_26_9"]].rename(
            columns={"MACD_12_26_9": "MACD", "MACDs_12_26_9": "Signal"}
        )


indicators_instance = Indicators()

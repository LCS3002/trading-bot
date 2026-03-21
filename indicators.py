"""
Technical indicator calculations via pandas-ta.
All methods return a new DataFrame and never mutate the input.
"""

import logging

import pandas as pd
import pandas_ta as ta

logger = logging.getLogger(__name__)


class Indicators:
    def get_rsi(self, df: pd.DataFrame, length: int = 14) -> pd.DataFrame:
        result = ta.rsi(df["close"], length=length)
        return pd.DataFrame({"RSI": result}, index=df.index)

    def get_ema(self, df: pd.DataFrame, length: int = 20) -> pd.DataFrame:
        result = ta.ema(df["close"], length=length)
        return pd.DataFrame({"EMA": result}, index=df.index)

    def get_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        result = ta.macd(df["close"])
        return result[["MACD_12_26_9", "MACDs_12_26_9"]].rename(
            columns={"MACD_12_26_9": "MACD", "MACDs_12_26_9": "Signal"}
        )


indicators_instance = Indicators()

"""
Strategy evaluation — computes technical indicators and produces a trading signal.

Default mode: MACD direction filtered by a 20-period EMA trend filter.
  BUY  when MACD > Signal  AND  close > EMA(20)
  SELL when MACD < Signal  AND  close < EMA(20)
  HOLD otherwise

Toggle behaviour via .env:  USE_MACD, USE_RSI, USE_EMA_FILTER
"""

import logging

import pandas as pd
from alpaca.data.timeframe import TimeFrame

from config import LOOKBACK_MINUTES, USE_EMA_FILTER, USE_MACD, USE_RSI
from data import stock_data_instance
from indicators import indicators_instance

logger = logging.getLogger(__name__)

_HOLD: dict = {
    "RSI": None,
    "EMA": None,
    "MACD": None,
    "Signal": None,
    "Decision": "HOLD",
    "ticker_data": None,
}


class Strategy:
    def _evaluate(self, ticker_data: pd.DataFrame) -> dict:
        """Core signal logic — shared by both polling and streaming paths."""
        rsi_df = indicators_instance.get_rsi(ticker_data)
        ema_df = indicators_instance.get_ema(ticker_data)
        macd_df = indicators_instance.get_macd(ticker_data)

        latest_rsi = rsi_df["RSI"].iloc[-1]
        latest_ema = ema_df["EMA"].iloc[-1]
        latest_close = ticker_data["close"].iloc[-1]
        latest_macd = macd_df["MACD"].iloc[-1]
        latest_signal = macd_df["Signal"].iloc[-1]

        if pd.isna(latest_macd) or pd.isna(latest_signal) or pd.isna(latest_ema):
            logger.warning("NaN indicator values — defaulting to HOLD")
            return {**_HOLD, "ticker_data": ticker_data}

        # EMA trend filter: only trade in the direction the price is trending
        above_ema = bool(latest_close > latest_ema) if USE_EMA_FILTER else True

        decision = "HOLD"

        if USE_MACD and USE_RSI:
            if not pd.isna(latest_rsi):
                if latest_rsi < 30 and latest_macd > latest_signal and above_ema:
                    decision = "BUY"
                elif latest_rsi > 70 and latest_macd < latest_signal and not above_ema:
                    decision = "SELL"
        elif USE_RSI:
            if not pd.isna(latest_rsi):
                if latest_rsi < 30 and above_ema:
                    decision = "BUY"
                elif latest_rsi > 70 and not above_ema:
                    decision = "SELL"
        elif USE_MACD:
            if latest_macd > latest_signal and above_ema:
                decision = "BUY"
            elif latest_macd < latest_signal and not above_ema:
                decision = "SELL"

        logger.debug(
            "MACD=%.4f  Signal=%.4f  EMA=%.2f  Close=%.2f  RSI=%s  → %s",
            latest_macd,
            latest_signal,
            latest_ema,
            latest_close,
            f"{latest_rsi:.1f}" if not pd.isna(latest_rsi) else "N/A",
            decision,
        )

        return {
            "RSI": latest_rsi,
            "EMA": latest_ema,
            "MACD": latest_macd,
            "Signal": latest_signal,
            "Decision": decision,
            "ticker_data": ticker_data,
        }

    def evaluate_strategy(self, ticker: str) -> dict:
        """Polling path: fetch historical bars then evaluate."""
        ticker_data = stock_data_instance.fetch_bars(
            ticker, TimeFrame.Minute, LOOKBACK_MINUTES
        )
        if ticker_data is None or ticker_data.empty:
            logger.warning("No data returned for %s — holding", ticker)
            return _HOLD
        return self._evaluate(ticker_data)

    def evaluate_streaming(self, ticker_data: pd.DataFrame) -> dict:
        """Streaming path: evaluate on a pre-filled DataFrame from the buffer."""
        if ticker_data is None or ticker_data.empty:
            return _HOLD
        return self._evaluate(ticker_data)


strategy_instance = Strategy()

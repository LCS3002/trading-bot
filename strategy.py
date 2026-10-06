"""
Strategy evaluation — computes technical indicators and produces a trading signal.

Default mode (USE_MACD, USE_EMA_FILTER): MACD direction, EMA(20) trend filter.
  BUY  when MACD > Signal  AND  close > EMA(20)
  SELL when MACD < Signal  AND  close < EMA(20)
  HOLD otherwise

With USE_RSI as well: MACD still sets direction, and RSI vetoes entries into an
already-stretched move (no BUY above RSI 70, no SELL below RSI 30).

With USE_RSI alone: pure mean reversion on RSI 30/70, with no trend filter —
oversold and uptrend are contradictory conditions.

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


RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70


class Strategy:
    def _evaluate(
        self,
        ticker_data: pd.DataFrame,
        *,
        use_macd: bool = USE_MACD,
        use_rsi: bool = USE_RSI,
        use_ema_filter: bool = USE_EMA_FILTER,
    ) -> dict:
        """Core signal logic — shared by both polling and streaming paths.

        The toggles are parameters (defaulting to the .env values) so the rules can be
        exercised directly in tests without reaching for environment variables.
        """
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

        # EMA trend filter: only trade in the direction the price is trending.
        # Tracked as two independent flags, not one boolean — with a single
        # `above_ema` flag, disabling the filter set it True and `not above_ema`
        # then made the SELL branch unreachable, silently turning the bot long-only.
        if use_ema_filter:
            trend_allows_long = bool(latest_close > latest_ema)
            trend_allows_short = bool(latest_close < latest_ema)
        else:
            trend_allows_long = trend_allows_short = True

        decision = "HOLD"

        if use_macd and use_rsi:
            # MACD sets direction; RSI acts as a veto on entering an already-stretched
            # move. RSI is deliberately not *required* to agree — demanding oversold
            # and a bullish crossover and an uptrend at once is near-unsatisfiable.
            rsi_blocks_long = not pd.isna(latest_rsi) and latest_rsi > RSI_OVERBOUGHT
            rsi_blocks_short = not pd.isna(latest_rsi) and latest_rsi < RSI_OVERSOLD

            if latest_macd > latest_signal and trend_allows_long and not rsi_blocks_long:
                decision = "BUY"
            elif (
                latest_macd < latest_signal
                and trend_allows_short
                and not rsi_blocks_short
            ):
                decision = "SELL"
        elif use_rsi:
            # Pure mean reversion. The EMA trend filter is deliberately NOT applied:
            # an oversold reading and an uptrend are contradictory by construction, so
            # requiring both made this branch fire almost never.
            if not pd.isna(latest_rsi):
                if latest_rsi < RSI_OVERSOLD:
                    decision = "BUY"
                elif latest_rsi > RSI_OVERBOUGHT:
                    decision = "SELL"
        elif use_macd:
            if latest_macd > latest_signal and trend_allows_long:
                decision = "BUY"
            elif latest_macd < latest_signal and trend_allows_short:
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
            return dict(_HOLD)
        return self._evaluate(ticker_data)

    def evaluate_streaming(self, ticker_data: pd.DataFrame, **overrides) -> dict:
        """Streaming path: evaluate on a pre-filled DataFrame from the buffer."""
        if ticker_data is None or ticker_data.empty:
            return dict(_HOLD)
        return self._evaluate(ticker_data, **overrides)


strategy_instance = Strategy()

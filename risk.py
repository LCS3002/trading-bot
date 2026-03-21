"""
Position sizing and ATR-based stop-loss calculation.
"""

import logging
import math
from typing import Optional, Tuple

import pandas as pd
import pandas_ta as ta
from alpaca.trading.client import TradingClient

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING

logger = logging.getLogger(__name__)

_trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)


class Risk:
    def get_account_info(self) -> Optional[dict]:
        try:
            account = _trading_client.get_account()
            return {
                "balance": float(account.equity),
                "buying_power": float(account.buying_power),
            }
        except Exception as e:
            logger.error("Failed to fetch account info: %s", e)
            return None

    def calculate_position_size(
        self,
        account_balance: float,
        risk_per_trade: float,
        current_price: float,
        stop_loss_distance: float,
    ) -> int:
        risk_amount = account_balance * risk_per_trade
        shares = int(risk_amount / stop_loss_distance) if stop_loss_distance > 0 else 1
        max_shares = int(account_balance / current_price)
        return max(min(shares, max_shares), 1)

    def calculate_atr_stop(
        self, ticker_data: pd.DataFrame, atr_multiplier: float = 2.0
    ) -> Optional[float]:
        if ticker_data is None or ticker_data.empty or len(ticker_data) < 20:
            return None

        atr = ta.atr(
            ticker_data["high"], ticker_data["low"], ticker_data["close"], length=14
        )
        if atr is None or atr.empty:
            return None

        val = float(atr.iloc[-1])
        if math.isnan(val) or val <= 0:
            return None

        return val * atr_multiplier

    def calculate_dynamic_position(
        self,
        account_balance: float,
        risk_per_trade: float,
        ticker_data: pd.DataFrame,
        current_price: float,
        atr_multiplier: float = 2.0,
    ) -> Tuple[Optional[int], Optional[float]]:
        stop_distance = self.calculate_atr_stop(ticker_data, atr_multiplier)
        if stop_distance is None:
            return None, None
        shares = self.calculate_position_size(
            account_balance, risk_per_trade, current_price, stop_distance
        )
        return shares, stop_distance


risk_instance = Risk()

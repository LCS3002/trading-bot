"""
Position sizing and ATR-based stop-loss calculation.

Sizing is bounded three ways: by the risk budget (equity × RISK_PER_TRADE ÷ stop
distance), by a notional cap (equity × MAX_POSITION_PCT), and by available buying
power. On a tight intraday ATR the risk budget alone asks for far more shares than
the account can responsibly hold, so the caps are what keep a position sane.
"""

import logging
import math
from typing import Optional, Tuple

import pandas as pd
from alpaca.trading.client import TradingClient

from indicators import indicators_instance

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    MAX_POSITION_PCT,
    PAPER_TRADING,
    require_credentials,
)

logger = logging.getLogger(__name__)

_trading_client: TradingClient | None = None


def _get_trading_client() -> TradingClient:
    """Built on first use. Only `get_account_info` needs it — the sizing and stop
    maths below are pure, and must import and unit-test without credentials."""
    global _trading_client
    if _trading_client is None:
        require_credentials()
        _trading_client = TradingClient(
            ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING
        )
    return _trading_client


class Risk:
    def get_account_info(self) -> Optional[dict]:
        try:
            account = _get_trading_client().get_account()
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
        buying_power: Optional[float] = None,
        max_position_pct: float = MAX_POSITION_PCT,
    ) -> int:
        """Shares to trade, or 0 when the account cannot support a position."""
        if current_price <= 0 or stop_loss_distance <= 0:
            return 0

        risk_budget = int((account_balance * risk_per_trade) / stop_loss_distance)
        notional_cap = int((account_balance * max_position_pct) / current_price)

        shares = min(risk_budget, notional_cap)
        if buying_power is not None:
            shares = min(shares, int(buying_power / current_price))

        if shares < risk_budget:
            logger.debug(
                "Size capped: risk budget wanted %d shares, capped to %d "
                "(%.0f%% notional / buying power)",
                risk_budget,
                shares,
                max_position_pct * 100,
            )

        return max(shares, 0)

    def calculate_atr_stop(
        self, ticker_data: pd.DataFrame, atr_multiplier: float = 2.0
    ) -> Optional[float]:
        if ticker_data is None or ticker_data.empty or len(ticker_data) < 20:
            return None

        atr = indicators_instance.get_atr(ticker_data, length=14)["ATR"]
        if atr.empty:
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
        buying_power: Optional[float] = None,
    ) -> Tuple[Optional[int], Optional[float]]:
        stop_distance = self.calculate_atr_stop(ticker_data, atr_multiplier)
        if stop_distance is None:
            return None, None
        shares = self.calculate_position_size(
            account_balance,
            risk_per_trade,
            current_price,
            stop_distance,
            buying_power=buying_power,
        )
        return shares, stop_distance


risk_instance = Risk()

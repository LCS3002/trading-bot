"""
Order execution — translates strategy signals into Alpaca market orders
and immediately places a protective stop-loss after every fill.
"""

import logging
from typing import Optional, Tuple

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, StopOrderRequest

from config import (
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ATR_MULTIPLIER,
    DYNAMIC_POSITION_SIZING,
    PAPER_TRADING,
    RISK_PER_TRADE,
)
from risk import risk_instance
from strategy import strategy_instance

logger = logging.getLogger(__name__)

_trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)


class Execution:
    # ── Position query ────────────────────────────────────────────────────────

    def get_current_position(self, ticker: str) -> Optional[int]:
        """Returns signed share count (negative = short, 0 = flat)."""
        try:
            position = _trading_client.get_open_position(ticker)
            return int(position.qty)
        except Exception as e:
            if "position does not exist" in str(e).lower():
                return 0
            logger.error("Could not retrieve position for %s: %s", ticker, e)
            return None

    # ── Sizing ────────────────────────────────────────────────────────────────

    def _size_position(
        self, ticker_data: pd.DataFrame, current_price: float
    ) -> Tuple[int, float]:
        """Returns (shares, stop_distance). Falls back to 1 share / 2% stop."""
        shares = 1
        stop_distance = 0.02 * current_price

        if DYNAMIC_POSITION_SIZING:
            account_info = risk_instance.get_account_info()
            if account_info:
                dynamic_shares, dynamic_stop = risk_instance.calculate_dynamic_position(
                    account_info["balance"],
                    RISK_PER_TRADE,
                    ticker_data,
                    current_price,
                    ATR_MULTIPLIER,
                )
                if dynamic_shares is not None and dynamic_stop is not None:
                    shares, stop_distance = dynamic_shares, dynamic_stop
            else:
                logger.warning("Account info unavailable — using static fallback sizing")

        return shares, stop_distance

    # ── Order helpers ─────────────────────────────────────────────────────────

    def _place_stop(
        self, ticker: str, shares: int, side: OrderSide, stop_price: float
    ) -> None:
        try:
            _trading_client.submit_order(
                StopOrderRequest(
                    symbol=ticker,
                    qty=shares,
                    side=side,
                    stop_price=round(stop_price, 2),
                    time_in_force=TimeInForce.DAY,
                )
            )
            logger.info(
                "Stop-loss placed | side=%s  price=$%.2f  qty=%d",
                side.value,
                stop_price,
                shares,
            )
        except Exception as e:
            logger.error("Stop-loss placement failed: %s", e)

    def _submit_and_protect(
        self,
        ticker: str,
        order_qty: int,
        order_side: OrderSide,
        stop_side: OrderSide,
        new_shares: int,
        stop_distance: float,
        is_buy: bool,
    ) -> None:
        """Submit a market order then immediately protect the new position."""
        try:
            order = _trading_client.submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    qty=order_qty,
                    side=order_side,
                    time_in_force=TimeInForce.DAY,
                )
            )
            logger.info(
                "%s order submitted | ticker=%s  qty=%d",
                order_side.value.upper(),
                ticker,
                order_qty,
            )

            fill_price = getattr(order, "filled_avg_price", None)
            if not fill_price:
                logger.warning("Order not immediately filled — skipping stop-loss")
                return

            entry_price = float(fill_price)
            stop_price = (
                entry_price - stop_distance if is_buy else entry_price + stop_distance
            )
            self._place_stop(ticker, new_shares, stop_side, stop_price)

        except Exception as e:
            logger.error(
                "%s order failed for %s: %s", order_side.value.upper(), ticker, e
            )

    # ── Core decision executor ────────────────────────────────────────────────

    def _execute_decision(
        self, ticker: str, ticker_data: pd.DataFrame, evaluation: dict
    ) -> dict:
        decision = evaluation["Decision"]
        current_position = self.get_current_position(ticker)

        if current_position is None:
            logger.error("Aborting — position unknown for %s", ticker)
            return evaluation

        current_price = float(ticker_data["close"].iloc[-1])
        shares, stop_distance = self._size_position(ticker_data, current_price)

        if decision == "BUY" and current_position <= 0:
            order_qty = abs(current_position) + shares if current_position < 0 else shares
            self._submit_and_protect(
                ticker, order_qty, OrderSide.BUY, OrderSide.SELL, shares, stop_distance, is_buy=True
            )
        elif decision == "SELL" and current_position >= 0:
            order_qty = abs(current_position) + shares if current_position > 0 else shares
            self._submit_and_protect(
                ticker, order_qty, OrderSide.SELL, OrderSide.BUY, shares, stop_distance, is_buy=False
            )
        else:
            logger.info(
                "HOLD | ticker=%s  position=%d  signal=%s",
                ticker,
                current_position,
                decision,
            )

        return evaluation

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_trade(self, ticker: str) -> dict:
        """Polling path: fetch data, evaluate, and execute."""
        evaluation = strategy_instance.evaluate_strategy(ticker)
        if evaluation["ticker_data"] is None:
            return evaluation
        return self._execute_decision(ticker, evaluation["ticker_data"], evaluation)

    def execute_streaming(self, ticker: str, ticker_data: pd.DataFrame) -> dict:
        """Streaming path: evaluate on buffered data and execute."""
        evaluation = strategy_instance.evaluate_streaming(ticker_data)
        if ticker_data is None or ticker_data.empty:
            return evaluation
        return self._execute_decision(ticker, ticker_data, evaluation)


execution_instance = Execution()

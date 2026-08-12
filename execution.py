"""
Order execution — translates strategy signals into Alpaca market orders and
protects every resulting position with a stop-loss.

Order lifecycle, in strict sequence:

    1. cancel any resting orders for the symbol (a stale stop from a previous
       entry would otherwise fire against the new position)
    2. submit the market order
    3. poll until it reaches a terminal state — submit_order() returns while the
       order is still `pending_new`, so the fill price is not available yet
    4. place the stop off the actual fill price; if that fails, flatten rather
       than hold unprotected exposure

Shorting is opt-in via ALLOW_SHORT. With it off, a SELL signal only closes an
open long — it never opens a short from flat.
"""

import logging
import time
from typing import Optional, Tuple

import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    MarketOrderRequest,
    StopOrderRequest,
)

from config import (
    ALLOW_SHORT,
    ALPACA_API_KEY,
    ALPACA_SECRET_KEY,
    ATR_MULTIPLIER,
    DYNAMIC_POSITION_SIZING,
    ORDER_FILL_TIMEOUT,
    PAPER_TRADING,
    RISK_PER_TRADE,
)
from risk import risk_instance
from strategy import strategy_instance

logger = logging.getLogger(__name__)

_trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

_TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELED,
    OrderStatus.EXPIRED,
    OrderStatus.REJECTED,
    OrderStatus.DONE_FOR_DAY,
}
_FILL_POLL_INTERVAL = 0.25  # seconds between fill checks


class Execution:
    # ── Position query ────────────────────────────────────────────────────────

    def get_current_position(self, ticker: str) -> Optional[int]:
        """Returns signed share count (negative = short, 0 = flat)."""
        try:
            position = _trading_client.get_open_position(ticker)
            return int(float(position.qty))
        except Exception as e:
            if "position does not exist" in str(e).lower():
                return 0
            logger.error("Could not retrieve position for %s: %s", ticker, e)
            return None

    # ── Sizing ────────────────────────────────────────────────────────────────

    def _size_position(
        self, ticker_data: pd.DataFrame, current_price: float
    ) -> Tuple[int, float]:
        """Returns (shares, stop_distance). (0, _) means do not trade."""
        if not DYNAMIC_POSITION_SIZING:
            return 1, 0.02 * current_price

        account_info = risk_instance.get_account_info()
        if not account_info:
            logger.warning("Account info unavailable — skipping trade")
            return 0, 0.0

        shares, stop_distance = risk_instance.calculate_dynamic_position(
            account_info["balance"],
            RISK_PER_TRADE,
            ticker_data,
            current_price,
            ATR_MULTIPLIER,
            buying_power=account_info["buying_power"],
        )
        if shares is None or stop_distance is None:
            logger.warning("ATR unavailable — skipping trade")
            return 0, 0.0

        return shares, stop_distance

    # ── Order helpers ─────────────────────────────────────────────────────────

    def _cancel_open_orders(self, ticker: str) -> None:
        """Clear resting orders so a stale stop cannot fire against a new position."""
        try:
            open_orders = _trading_client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker])
            )
        except Exception as e:
            logger.error("Could not list open orders for %s: %s", ticker, e)
            return

        cancelled = False
        for order in open_orders:
            try:
                _trading_client.cancel_order_by_id(order.id)
                cancelled = True
                logger.info(
                    "Cancelled resting %s order | id=%s  qty=%s",
                    order.side.value,
                    order.id,
                    order.qty,
                )
            except Exception as e:
                logger.warning("Could not cancel order %s: %s", order.id, e)

        if cancelled:
            self._await_cancellation(ticker)

    def _await_cancellation(self, ticker: str, timeout: float = 3.0) -> None:
        """Cancellation is asynchronous — an order still in `pending_cancel` will
        get the next opposite-side order rejected as a potential wash trade."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                still_open = _trading_client.get_orders(
                    GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[ticker])
                )
            except Exception as e:
                logger.warning("Could not confirm cancellation for %s: %s", ticker, e)
                return
            if not still_open:
                return
            time.sleep(0.25)

        logger.warning(
            "Orders for %s still resting after cancel — next order may be rejected",
            ticker,
        )

    def _wait_for_fill(self, order_id) -> Tuple[int, Optional[float]]:
        """Poll an order to a terminal state. Returns (filled_qty, avg_fill_price)."""
        deadline = time.monotonic() + ORDER_FILL_TIMEOUT
        order = None

        while True:
            try:
                order = _trading_client.get_order_by_id(order_id)
            except Exception as e:
                logger.error("Could not poll order %s: %s", order_id, e)
                return 0, None

            if order.status in _TERMINAL_STATUSES:
                break
            if time.monotonic() >= deadline:
                logger.error(
                    "Order %s still %s after %.0fs — leaving it working, no stop placed",
                    order_id,
                    order.status.value,
                    ORDER_FILL_TIMEOUT,
                )
                break
            time.sleep(_FILL_POLL_INTERVAL)

        filled_qty = int(float(order.filled_qty or 0))
        fill_price = (
            float(order.filled_avg_price) if order.filled_avg_price else None
        )

        if filled_qty and order.status != OrderStatus.FILLED:
            logger.warning(
                "Order %s partially filled: %d of %s shares (status=%s)",
                order_id,
                filled_qty,
                order.qty,
                order.status.value,
            )
        elif not filled_qty:
            logger.warning(
                "Order %s did not fill (status=%s)", order_id, order.status.value
            )

        return filled_qty, fill_price

    def _submit_market(
        self, ticker: str, qty: int, side: OrderSide
    ) -> Tuple[int, Optional[float]]:
        """Submit a market order and block until it fills or reaches a dead end."""
        try:
            order = _trading_client.submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=side,
                    time_in_force=TimeInForce.DAY,
                )
            )
        except Exception as e:
            logger.error("%s order failed for %s: %s", side.value.upper(), ticker, e)
            return 0, None

        logger.info(
            "%s order submitted | ticker=%s  qty=%d", side.value.upper(), ticker, qty
        )
        filled_qty, fill_price = self._wait_for_fill(order.id)

        if filled_qty:
            logger.info(
                "%s filled | ticker=%s  qty=%d  price=%s",
                side.value.upper(),
                ticker,
                filled_qty,
                f"${fill_price:.2f}" if fill_price else "n/a",
            )
        return filled_qty, fill_price

    def _place_stop(
        self, ticker: str, shares: int, side: OrderSide, stop_price: float
    ) -> bool:
        for attempt in (1, 2):
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
                return True
            except Exception as e:
                logger.error("Stop-loss placement failed (attempt %d): %s", attempt, e)
                if attempt == 1:
                    time.sleep(1)
        return False

    # ── Position transitions ──────────────────────────────────────────────────

    def _flatten(self, ticker: str, position: int, reason: str) -> None:
        """Close an open position at market and clear its protective stop."""
        side = OrderSide.SELL if position > 0 else OrderSide.BUY
        self._cancel_open_orders(ticker)
        filled, _ = self._submit_market(ticker, abs(position), side)
        if filled:
            logger.info(
                "Position closed | ticker=%s  qty=%d  reason=%s", ticker, filled, reason
            )

    def _enter(
        self,
        ticker: str,
        ticker_data: pd.DataFrame,
        current_price: float,
        side: OrderSide,
        position: int,
    ) -> None:
        """Open a position (reversing any opposite-side one) and protect it."""
        shares, stop_distance = self._size_position(ticker_data, current_price)
        if shares <= 0:
            logger.warning("Trade skipped — sizing returned 0 shares")
            return

        self._cancel_open_orders(ticker)

        # An opposite-side position must be bought/sold back before the new one opens.
        cover_qty = abs(position)
        filled, fill_price = self._submit_market(ticker, cover_qty + shares, side)
        if not filled:
            return

        new_shares = filled - cover_qty
        if new_shares <= 0:
            logger.warning(
                "Fill only covered the existing position — no new exposure to protect"
            )
            return

        if fill_price is None:
            logger.warning("No fill price returned — stopping off last close instead")
        entry_price = fill_price if fill_price is not None else current_price

        is_long = side == OrderSide.BUY
        stop_price = (
            entry_price - stop_distance if is_long else entry_price + stop_distance
        )
        stop_side = OrderSide.SELL if is_long else OrderSide.BUY

        if not self._place_stop(ticker, new_shares, stop_side, stop_price):
            logger.error(
                "Could not protect %d %s shares — flattening rather than running naked",
                new_shares,
                ticker,
            )
            self._flatten(
                ticker, new_shares if is_long else -new_shares, "stop placement failed"
            )

    # ── Core decision executor ────────────────────────────────────────────────

    def _execute_decision(
        self, ticker: str, ticker_data: pd.DataFrame, evaluation: dict
    ) -> dict:
        decision = evaluation["Decision"]
        position = self.get_current_position(ticker)

        if position is None:
            logger.error("Aborting — position unknown for %s", ticker)
            return evaluation

        current_price = float(ticker_data["close"].iloc[-1])

        if decision == "BUY" and position <= 0:
            # Covers an existing short first, then opens the long.
            self._enter(ticker, ticker_data, current_price, OrderSide.BUY, position)
        elif decision == "SELL" and position > 0:
            self._flatten(ticker, position, "sell signal")
        elif decision == "SELL" and position == 0 and ALLOW_SHORT:
            self._enter(ticker, ticker_data, current_price, OrderSide.SELL, position)
        else:
            logger.info(
                "HOLD | ticker=%s  position=%d  signal=%s", ticker, position, decision
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
        if ticker_data is None or ticker_data.empty:
            return strategy_instance.evaluate_streaming(ticker_data)
        evaluation = strategy_instance.evaluate_streaming(ticker_data)
        return self._execute_decision(ticker, ticker_data, evaluation)


execution_instance = Execution()

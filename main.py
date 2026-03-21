"""
Polling entry point.
Evaluates the strategy every 60 seconds using the last N minutes of REST bar data.
"""

import logging
import time

from alpaca.trading.client import TradingClient

import config  # noqa: F401 — initialises logging and validates credentials
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, PAPER_TRADING
from execution import execution_instance

logger = logging.getLogger(__name__)

_trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

BASE_SLEEP = 60       # seconds between cycles
MAX_SLEEP = 15 * 60   # cap for exponential backoff


def run(ticker: str) -> None:
    backoff = BASE_SLEEP
    logger.info("Polling bot started | ticker=%s  paper=%s", ticker, PAPER_TRADING)

    while True:
        try:
            clock = _trading_client.get_clock()
            if not clock.is_open:
                logger.info("Market closed — sleeping %ds", BASE_SLEEP)
                time.sleep(BASE_SLEEP)
                continue

            result = execution_instance.execute_trade(ticker)
            logger.info(
                "Cycle complete | decision=%-4s  MACD=%s  RSI=%s",
                result.get("Decision", "N/A"),
                f"{result['MACD']:.4f}" if result.get("MACD") is not None else "N/A",
                f"{result['RSI']:.1f}" if result.get("RSI") is not None else "N/A",
            )
            backoff = BASE_SLEEP
            time.sleep(BASE_SLEEP)

        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("Loop error: %s — backing off %ds", e, backoff)
            time.sleep(backoff)
            backoff = min(int(backoff * 2), MAX_SLEEP)


if __name__ == "__main__":
    ticker = input("Enter ticker symbol: ").upper().strip()
    try:
        run(ticker)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down.")

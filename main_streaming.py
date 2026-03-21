"""
Streaming entry point.
Pre-fills the bar buffer with historical data at startup, then subscribes to the
real-time Alpaca bar stream. The bot is ready to trade on the very first live bar
with no warmup wait.

If the historical prefill fails the bot falls back to the streaming warmup
(WARMUP_BARS bars collected before trading begins).
"""

import asyncio
import logging

from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient

import config  # noqa: F401 — initialises logging and validates credentials
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, LOOKBACK_MINUTES, PAPER_TRADING
from data import stock_data_instance
from data_buffer_methods import data_buffer
from execution import execution_instance
from hybrid_data import HybridData, run_stream

logger = logging.getLogger(__name__)

_trading_client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=PAPER_TRADING)

_POLL_INTERVAL = 0.5   # seconds between buffer checks when no new bar has arrived
_CLOSED_SLEEP = 60     # seconds to wait when market is closed


async def trade_loop(symbol: str) -> None:
    last_ts = None

    while True:
        try:
            clock = _trading_client.get_clock()
            if not clock.is_open:
                logger.info("Market closed — sleeping %ds", _CLOSED_SLEEP)
                await asyncio.sleep(_CLOSED_SLEEP)
                continue

            if not data_buffer.is_ready():
                await asyncio.sleep(1)
                continue

            df = data_buffer.get_latest_data()
            if df.empty:
                await asyncio.sleep(1)
                continue

            latest_ts = df.index[-1]
            if last_ts is not None and latest_ts == last_ts:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            last_ts = latest_ts
            result = execution_instance.execute_streaming(symbol, df)

            if result:
                logger.info(
                    "Bar %s | decision=%-4s  MACD=%s  EMA=%s",
                    latest_ts,
                    result.get("Decision", "N/A"),
                    f"{result['MACD']:.4f}" if result.get("MACD") is not None else "N/A",
                    f"{result['EMA']:.2f}" if result.get("EMA") is not None else "N/A",
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("trade_loop error: %s", e)
            await asyncio.sleep(2)


async def main_async(symbol: str) -> None:
    # Pre-fill buffer with historical bars so indicators are ready immediately.
    # Falls back to streaming warmup if the fetch fails (e.g. market closed, API error).
    logger.info("Fetching historical bars for %s to prime the buffer...", symbol)
    hist_df = stock_data_instance.fetch_bars(symbol, TimeFrame.Minute, LOOKBACK_MINUTES)
    data_buffer.prefill(hist_df)

    hybrid = HybridData(symbol=symbol, buffer=data_buffer)
    stream_task = asyncio.create_task(run_stream(symbol, data_buffer, hybrid))
    trade_task = asyncio.create_task(trade_loop(symbol))

    try:
        await asyncio.gather(stream_task, trade_task)
    except asyncio.CancelledError:
        pass
    finally:
        await hybrid.stop()
        for task in (stream_task, trade_task):
            if not task.cancelled():
                task.cancel()


def main() -> None:
    symbol = input("Enter ticker symbol: ").upper().strip()
    logger.info("Streaming bot started | ticker=%s  paper=%s", symbol, PAPER_TRADING)
    try:
        asyncio.run(main_async(symbol))
    except KeyboardInterrupt:
        logger.info("Stopping streaming bot.")


if __name__ == "__main__":
    main()

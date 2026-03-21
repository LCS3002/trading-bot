"""
Real-time bar subscription via the Alpaca WebSocket stream.
Feeds incoming bars directly into a DataBuffer.
"""

import asyncio
import logging

from alpaca.data.live import StockDataStream

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from data_buffer_methods import DataBuffer

logger = logging.getLogger(__name__)


class HybridData:
    """Subscribes to a live Alpaca bar stream and populates a DataBuffer."""

    def __init__(self, symbol: str, buffer: DataBuffer) -> None:
        self.symbol = symbol
        self.buffer = buffer
        self.stream = StockDataStream(ALPACA_API_KEY, ALPACA_SECRET_KEY)

    async def _on_bar(self, bar) -> None:
        self.buffer.append_realtime(bar)

    async def start(self) -> None:
        self.stream.subscribe_bars(self._on_bar, self.symbol)
        logger.info("Stream subscribed for %s", self.symbol)
        await asyncio.to_thread(self.stream.run)

    async def stop(self) -> None:
        await asyncio.to_thread(self.stream.stop)
        logger.info("Stream stopped for %s", self.symbol)


async def run_stream(
    symbol: str, buffer: DataBuffer, hybrid_instance: HybridData
) -> None:
    try:
        await hybrid_instance.start()
    finally:
        await hybrid_instance.stop()

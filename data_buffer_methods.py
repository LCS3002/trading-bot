"""
Rolling bar buffer for real-time streaming data.
Can be pre-filled with historical bars to skip the streaming warmup period entirely.
"""

import logging

import pandas as pd

from config import WARMUP_BARS

logger = logging.getLogger(__name__)


class DataBuffer:
    def __init__(self, warmup_bars: int = WARMUP_BARS, max_bars: int = 1000) -> None:
        self.bars = pd.DataFrame()
        self.warmup_complete = False
        self.warmup_bars = warmup_bars
        self._collected = 0
        self.max_bars = max_bars

    def append_realtime(self, bar) -> None:
        new_row = pd.DataFrame(
            {
                "open": [bar.open],
                "high": [bar.high],
                "low": [bar.low],
                "close": [bar.close],
                "volume": [bar.volume],
            },
            index=[bar.timestamp],
        )
        self.bars = pd.concat([self.bars, new_row])

        if len(self.bars) > self.max_bars:
            self.bars = self.bars.iloc[-self.max_bars :]

        if not self.warmup_complete:
            self._collected += 1
            logger.info("Warmup: %d / %d bars", self._collected, self.warmup_bars)
            if self._collected >= self.warmup_bars:
                self.warmup_complete = True
                logger.info("Warmup complete — live trading now active")

    def prefill(self, df: pd.DataFrame) -> None:
        """Load historical bars into the buffer and mark warmup complete immediately."""
        if df is None or df.empty:
            logger.warning("Prefill skipped — no historical data returned")
            return
        self.bars = df.iloc[-self.max_bars :].copy()
        self._collected = len(self.bars)
        self.warmup_complete = True
        logger.info("Buffer prefilled with %d historical bars — ready to trade", len(self.bars))

    def get_latest_data(self) -> pd.DataFrame:
        return self.bars.copy()

    def is_ready(self) -> bool:
        return self.warmup_complete and len(self.bars) >= self.warmup_bars


data_buffer = DataBuffer()

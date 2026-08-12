"""
Rolling bar buffer for real-time streaming data.
Can be pre-filled with historical bars to skip the streaming warmup period entirely.

Every write goes through _merge(), so the buffer always holds a sorted, unique
DatetimeIndex regardless of whether the bars came from REST or the WebSocket.
"""

import logging

import pandas as pd

from config import WARMUP_BARS
from data import BAR_COLUMNS, normalise_bars

logger = logging.getLogger(__name__)


class DataBuffer:
    def __init__(self, warmup_bars: int = WARMUP_BARS, max_bars: int = 1000) -> None:
        self.bars = pd.DataFrame(columns=BAR_COLUMNS)
        self.warmup_complete = False
        self.warmup_bars = warmup_bars
        self._collected = 0
        self.max_bars = max_bars

    # ── Internal ──────────────────────────────────────────────────────────────

    def _merge(self, new_rows: pd.DataFrame) -> int:
        """Merge rows into the buffer. Returns the number of new timestamps added."""
        new_rows = normalise_bars(new_rows)
        if new_rows.empty:
            return 0

        added = len(new_rows.index.difference(self.bars.index))
        combined = pd.concat([self.bars, new_rows]) if len(self.bars) else new_rows

        # keep="last" lets a corrected REST bar overwrite the streamed one.
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        self.bars = combined.iloc[-self.max_bars :]

        return added

    # ── Writes ────────────────────────────────────────────────────────────────

    def append_realtime(self, bar) -> None:
        new_row = pd.DataFrame(
            {
                "open": [bar.open],
                "high": [bar.high],
                "low": [bar.low],
                "close": [bar.close],
                "volume": [bar.volume],
            },
            index=pd.DatetimeIndex([bar.timestamp], name="timestamp"),
        )
        self._merge(new_row)

        if not self.warmup_complete:
            self._collected += 1
            logger.info("Warmup: %d / %d bars", self._collected, self.warmup_bars)
            if self._collected >= self.warmup_bars:
                self.warmup_complete = True
                logger.info("Warmup complete — live trading now active")

    def add_bars(self, df: pd.DataFrame) -> int:
        """Merge historical bars into an already-running buffer (gap backfill)."""
        return self._merge(df)

    def prefill(self, df: pd.DataFrame) -> None:
        """Load historical bars into the buffer and mark warmup complete immediately."""
        if df is None or df.empty:
            logger.warning("Prefill skipped — no historical data returned")
            return

        self._merge(df)
        self._collected = len(self.bars)
        self.warmup_complete = True
        logger.info(
            "Buffer prefilled with %d historical bars — ready to trade", len(self.bars)
        )

    # ── Reads ─────────────────────────────────────────────────────────────────

    def get_latest_data(self) -> pd.DataFrame:
        return self.bars.copy()

    def is_ready(self) -> bool:
        return self.warmup_complete and len(self.bars) >= self.warmup_bars


data_buffer = DataBuffer()

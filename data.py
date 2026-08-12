"""
Historical bar fetching via the Alpaca REST API.

Everything leaving this module carries a plain, sorted, UTC DatetimeIndex — never
the (symbol, timestamp) MultiIndex alpaca-py returns — so REST bars and streamed
bars share one shape and can be concatenated safely.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, DATA_FEED

logger = logging.getLogger(__name__)

_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)

BAR_COLUMNS = ["open", "high", "low", "close", "volume"]

# Warn when the newest historical bar is older than this — on the free tier it
# will be ~15 minutes, which leaves a hole between the prefill and the stream.
_STALE_BAR_MINUTES = 5


def normalise_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten to a sorted, de-duplicated, UTC DatetimeIndex of OHLCV columns."""
    if df is None or df.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)

    df = df.copy()

    if isinstance(df.index, pd.MultiIndex):
        level = "symbol" if "symbol" in (df.index.names or []) else 0
        df = df.droplevel(level)

    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    df = df[~df.index.duplicated(keep="last")].sort_index()

    return df[[c for c in BAR_COLUMNS if c in df.columns]]


class StockData:
    def __init__(self) -> None:
        self.client = _client

    def fetch_bars(
        self, ticker: str, timeframe: TimeFrame, lookback_minutes: int
    ) -> pd.DataFrame:
        start = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

        # No `end` — the API clamps to the newest bar the subscription allows.
        # Passing a now-timestamp on a delayed feed just risks a 403.
        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=timeframe,
            start=start,
            feed=DataFeed(DATA_FEED),
        )

        try:
            df = normalise_bars(self.client.get_stock_bars(request).df)
            if df.empty:
                logger.warning("No bars returned for %s", ticker)
                return df

            age_minutes = (
                datetime.now(timezone.utc) - df.index[-1]
            ).total_seconds() / 60
            if age_minutes > _STALE_BAR_MINUTES:
                logger.warning(
                    "Newest %s bar is %.0f min old — the %s feed is delayed; "
                    "the periodic backfill will close the gap",
                    ticker,
                    age_minutes,
                    DATA_FEED.upper(),
                )

            logger.debug(
                "Fetched %d bars for %s (%s → %s)",
                len(df),
                ticker,
                df.index[0],
                df.index[-1],
            )
            return df
        except Exception as e:
            logger.error("fetch_bars failed for %s: %s", ticker, e)
            return pd.DataFrame(columns=BAR_COLUMNS)


stock_data_instance = StockData()

"""
Historical bar fetching via the Alpaca REST API.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import ALPACA_API_KEY, ALPACA_SECRET_KEY

logger = logging.getLogger(__name__)

_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)


class StockData:
    def __init__(self) -> None:
        self.client = _client

    def fetch_bars(
        self, ticker: str, timeframe: TimeFrame, lookback_minutes: int
    ) -> pd.DataFrame:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=lookback_minutes)

        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=timeframe,
            time_start=start,
            time_end=end,
        )

        try:
            bars = self.client.get_stock_bars(request)
            df = bars.df
            if df.empty:
                logger.warning("No bars returned for %s", ticker)
                return pd.DataFrame()
            logger.debug("Fetched %d bars for %s", len(df), ticker)
            return df
        except Exception as e:
            logger.error("fetch_bars failed for %s: %s", ticker, e)
            return pd.DataFrame()


stock_data_instance = StockData()

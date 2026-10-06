"""
Central configuration — loads .env once and exposes typed constants.
All other modules import from here; nothing else calls load_dotenv().
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
ALPACA_API_KEY: str = os.getenv("API_KEY", "")
ALPACA_SECRET_KEY: str = os.getenv("SECRET_KEY", "")


def require_credentials() -> None:
    """Assert credentials are present. Called by the entry points, not at import.

    Importing this module must never raise: the indicator, strategy and sizing logic
    is pure and has to be importable — and unit-testable — without Alpaca keys.
    """
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError(
            "Missing Alpaca credentials. Copy .env.example → .env and fill in your keys."
        )

# ── Trading mode ──────────────────────────────────────────────────────────────
PAPER_TRADING: bool = os.getenv("PAPER_TRADING", "true").lower() == "true"

# ── Strategy toggles ──────────────────────────────────────────────────────────
USE_MACD: bool = os.getenv("USE_MACD", "true").lower() == "true"
USE_RSI: bool = os.getenv("USE_RSI", "false").lower() == "true"
USE_EMA_FILTER: bool = os.getenv("USE_EMA_FILTER", "true").lower() == "true"

# ── Risk management ───────────────────────────────────────────────────────────
RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "0.02"))
ATR_MULTIPLIER: float = float(os.getenv("ATR_MULTIPLIER", "2.0"))
DYNAMIC_POSITION_SIZING: bool = os.getenv("DYNAMIC_POSITION_SIZING", "true").lower() == "true"

# When false a SELL signal only closes an open long — it never opens a short
# from flat. Enabled by default: the strategy is a reversal system.
ALLOW_SHORT: bool = os.getenv("ALLOW_SHORT", "true").lower() == "true"

# Hard cap on a single position's notional value, as a fraction of equity.
MAX_POSITION_PCT: float = float(os.getenv("MAX_POSITION_PCT", "0.25"))

# Seconds to wait for a market order to fill before giving up on it.
ORDER_FILL_TIMEOUT: float = float(os.getenv("ORDER_FILL_TIMEOUT", "10"))

# ── Data settings ─────────────────────────────────────────────────────────────
LOOKBACK_MINUTES: int = int(os.getenv("LOOKBACK_MINUTES", "300"))
WARMUP_BARS: int = int(os.getenv("WARMUP_BARS", "50"))

# "iex" (free tier) or "sip" (Algo Trader Plus). Applies to REST and the stream.
DATA_FEED: str = os.getenv("DATA_FEED", "iex").lower()

# Seconds between REST backfills that repair gaps left by delayed historical data.
BACKFILL_INTERVAL: int = int(os.getenv("BACKFILL_INTERVAL", "60"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)-28s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

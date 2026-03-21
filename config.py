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

# ── Data settings ─────────────────────────────────────────────────────────────
LOOKBACK_MINUTES: int = int(os.getenv("LOOKBACK_MINUTES", "300"))
WARMUP_BARS: int = int(os.getenv("WARMUP_BARS", "50"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)-28s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

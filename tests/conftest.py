"""Put the repo root on sys.path so tests import the modules as the bot does.

Nothing here supplies credentials: every module under test must import without them.
`tests/test_offline_import.py` asserts that invariant explicitly.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def make_bars(closes, highs=None, lows=None, volumes=None, start="2026-01-02 14:30"):
    """An OHLCV frame in the shape data.normalise_bars guarantees: lowercase columns,
    sorted tz-aware UTC DatetimeIndex named `timestamp`."""
    n = len(closes)
    idx = pd.date_range(start=start, periods=n, freq="1min", tz="UTC", name="timestamp")
    return pd.DataFrame(
        {
            "open": closes,
            "high": highs if highs is not None else [c + 0.5 for c in closes],
            "low": lows if lows is not None else [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes if volumes is not None else [1000] * n,
        },
        index=idx,
    )


@pytest.fixture
def bars():
    return make_bars

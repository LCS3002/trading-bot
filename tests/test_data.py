"""`normalise_bars` is the schema contract every other module depends on: REST bars and
streamed bars are concatenated on the assumption that it already made them the same
shape. These tests pin that contract down."""

import pandas as pd
import pytest

from data import BAR_COLUMNS, normalise_bars


def _multi_index_frame():
    """The shape alpaca-py actually returns: a (symbol, timestamp) MultiIndex."""
    idx = pd.MultiIndex.from_tuples(
        [
            ("AAPL", pd.Timestamp("2026-01-02 14:31", tz="UTC")),
            ("AAPL", pd.Timestamp("2026-01-02 14:30", tz="UTC")),
        ],
        names=["symbol", "timestamp"],
    )
    return pd.DataFrame(
        {
            "open": [2.0, 1.0],
            "high": [2.5, 1.5],
            "low": [1.5, 0.5],
            "close": [2.1, 1.1],
            "volume": [200, 100],
        },
        index=idx,
    )


def test_drops_the_symbol_level_and_sorts_by_time():
    out = normalise_bars(_multi_index_frame())

    assert not isinstance(out.index, pd.MultiIndex)
    assert out.index.is_monotonic_increasing
    assert out["close"].tolist() == [1.1, 2.1]


def test_index_is_utc_aware_and_named_timestamp():
    out = normalise_bars(_multi_index_frame())

    assert out.index.name == "timestamp"
    assert isinstance(out.index, pd.DatetimeIndex)
    assert str(out.index.tz) == "UTC"


def test_duplicate_timestamps_keep_the_last_row():
    """A REST backfill bar must win over the streamed bar it corrects."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-01-02 14:30", tz="UTC")] * 2, name="timestamp"
    )
    df = pd.DataFrame(
        {
            "open": [1.0, 9.0],
            "high": [1.0, 9.0],
            "low": [1.0, 9.0],
            "close": [1.0, 9.0],
            "volume": [1, 2],
        },
        index=idx,
    )

    out = normalise_bars(df)
    assert len(out) == 1
    assert out["close"].iloc[0] == 9.0


def test_projects_to_bar_columns_and_drops_extras():
    df = _multi_index_frame().droplevel("symbol")
    df["trade_count"] = [5, 6]
    df["vwap"] = [1.0, 2.0]

    assert list(normalise_bars(df).columns) == BAR_COLUMNS


@pytest.mark.parametrize("empty", [None, pd.DataFrame()])
def test_empty_input_yields_an_empty_frame_with_the_right_columns(empty):
    out = normalise_bars(empty)

    assert out.empty
    assert list(out.columns) == BAR_COLUMNS


def test_naive_timestamps_are_localised_to_utc():
    idx = pd.DatetimeIndex(["2026-01-02 14:30", "2026-01-02 14:31"], name="timestamp")
    df = pd.DataFrame(
        {"open": [1.0, 2.0], "high": [1, 2], "low": [1, 2], "close": [1.0, 2.0],
         "volume": [1, 2]},
        index=idx,
    )

    assert str(normalise_bars(df).index.tz) == "UTC"


def test_does_not_mutate_its_input():
    df = _multi_index_frame()
    before = df.copy(deep=True)

    normalise_bars(df)
    assert df.equals(before)

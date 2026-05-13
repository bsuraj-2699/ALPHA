"""RSI dual-field + intraday alias behaviour."""

from __future__ import annotations

import numpy as np
import pandas as pd

from packages.data.context_builder import _indicators_from_bars
from packages.data.providers.technicals import compute_indicators


def _bars_from_df(df: pd.DataFrame) -> list:
    class Row:
        __slots__ = ("timestamp", "open", "high", "low", "close", "volume")

        def __init__(self, ts, o, h, l, c, v):
            self.timestamp = ts
            self.open = o
            self.high = h
            self.low = l
            self.close = c
            self.volume = v

    out = []
    for ts, row in df.iterrows():
        out.append(
            Row(
                ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                float(row["Volume"]),
            )
        )
    return out


def test_compute_indicators_emits_rsi_14_and_rsi_3() -> None:
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    rng = np.random.default_rng(0)
    c = 100 + np.cumsum(rng.normal(0, 0.5, 200))
    df = pd.DataFrame(
        {
            "Open": c,
            "High": c + 1,
            "Low": c - 1,
            "Close": c,
            "Volume": np.full(200, 1e6),
        },
        index=idx,
    )
    out = compute_indicators(df)
    assert "rsi_14" in out
    assert "rsi_3" in out


def test_intraday_alias_sets_rsi_14_from_rsi_3() -> None:
    idx = pd.date_range("2020-01-01", periods=200, freq="B")
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.5, 200))
    df = pd.DataFrame(
        {
            "Open": c,
            "High": c + 1,
            "Low": c - 1,
            "Close": c,
            "Volume": np.full(200, 1e6),
        },
        index=idx,
    )
    bars = _bars_from_df(df)
    plain = _indicators_from_bars(bars, None)
    intra = _indicators_from_bars(bars, "intraday")
    assert abs(intra["rsi_14"] - intra["rsi_3"]) < 1e-9
    assert abs(plain["rsi_14"] - plain["rsi_3"]) > 1e-6

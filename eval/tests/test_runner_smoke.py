"""Smoke test for the full BacktestRunner with injected (offline) frames.

We don't hit yfinance in CI - we synthesise a deterministic OHLC frame
that's long enough for ``compute_indicators`` to fire (>200 days for
SMAs) and feed it directly. Asserts:

  * the runner completes without raising
  * an equity curve is produced
  * benchmarks attach
  * the decision log isn't empty
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from eval.historical_context import HistoricalFrames, INDEX_SYMBOL, VIX_SYMBOL
from eval.runner import BacktestConfig, BacktestRunner, BacktestSpec


def _synth_ohlc(
    n_days: int = 280,
    start_price: float = 100.0,
    drift: float = 0.0008,
    vol: float = 0.012,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=n_days)
    closes = start_price * np.exp(np.cumsum(rets))
    highs = closes * (1.0 + np.abs(rng.normal(0.005, 0.003, n_days)))
    lows = closes * (1.0 - np.abs(rng.normal(0.005, 0.003, n_days)))
    opens = closes * (1.0 + rng.normal(0.0, 0.003, n_days))
    vol_series = rng.integers(800_000, 1_500_000, size=n_days).astype(float)

    idx = pd.date_range(end=date.today() - timedelta(days=1), periods=n_days, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vol_series},
        index=idx,
    )


@pytest.mark.asyncio
async def test_runner_smoke_with_offline_frames() -> None:
    n_days = 280
    stock = _synth_ohlc(n_days=n_days, drift=0.0010, seed=7)
    market = _synth_ohlc(n_days=n_days, drift=0.0006, seed=11, start_price=4500)
    vix = _synth_ohlc(n_days=n_days, drift=0.0, vol=0.04, seed=13, start_price=18)

    frames_for_aapl = HistoricalFrames(
        frames={
            "RELIANCE.NS": stock,
            INDEX_SYMBOL["IN"]: market,
            VIX_SYMBOL["IN"]: vix,
        }
    )

    # Backtest the trailing 30 trading days
    backtest_start = stock.index[-30].date()
    backtest_end = stock.index[-1].date()

    spec = BacktestSpec(
        ticker="RELIANCE.NS", market="IN",
        start_date=backtest_start, end_date=backtest_end,
    )
    runner = BacktestRunner(
        specs=[spec],
        config=BacktestConfig(
            starting_capital=100_000,
            decision_cadence_days=5,
            fetch_frames=False,
        ),
        frames={"RELIANCE.NS": frames_for_aapl},
    )

    result = await runner.run_async()

    assert result.summary is not None
    assert result.equity_curve, "expected at least one equity-curve point"
    # Strategy curve length matches trading days in window
    assert 25 <= len(result.equity_curve) <= 35
    # Benchmarks attached
    assert result.benchmark_basket is not None
    assert result.benchmark_index is not None
    # Decision cadence: 30 days / 5 cadence ~= 6 decisions
    assert 4 <= result.decisions_emitted <= 8
    # Final ending value is positive
    assert result.summary.ending_value > 0

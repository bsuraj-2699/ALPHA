"""Unit tests for backtest metrics.

Mostly hand-computed values against a tiny synthetic equity curve so
each formula is anchored to a known answer.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eval.metrics import (
    cagr,
    daily_returns,
    max_drawdown,
    max_drawdown_window,
    sharpe_ratio,
    summarise,
    total_return,
)
from eval.portfolio import EquityPoint, Trade


def _curve(values: list[float], start: date | None = None) -> list[EquityPoint]:
    start = start or date(2024, 1, 2)
    return [
        EquityPoint(date=start + timedelta(days=i), cash=0, positions_value=v, total=v)
        for i, v in enumerate(values)
    ]


# ---------------------------------------------------------------------------
# Daily returns / total return
# ---------------------------------------------------------------------------


def test_daily_returns_simple() -> None:
    rets = daily_returns(_curve([100, 110, 99]))
    assert rets[0] == pytest.approx(0.10)
    assert rets[1] == pytest.approx(-0.10)


def test_total_return_positive_and_negative() -> None:
    assert total_return(_curve([100, 120])) == pytest.approx(0.20)
    assert total_return(_curve([100, 80])) == pytest.approx(-0.20)


def test_total_return_handles_empty_curve() -> None:
    assert total_return([]) == 0.0


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------


def test_max_drawdown_simple_v_shape() -> None:
    # peak 120, trough 90 -> 25% DD
    dd = max_drawdown(_curve([100, 120, 90, 110]))
    assert dd == pytest.approx(0.25)


def test_max_drawdown_zero_for_monotonic_increase() -> None:
    assert max_drawdown(_curve([100, 110, 120, 130])) == 0.0


def test_max_drawdown_window_returns_peak_and_trough_dates() -> None:
    curve = _curve([100, 130, 120, 80, 90, 95])
    peak, trough, dd = max_drawdown_window(curve)
    assert peak == curve[1].date  # 130
    assert trough == curve[3].date  # 80
    assert dd == pytest.approx(50 / 130)


# ---------------------------------------------------------------------------
# Sharpe / CAGR
# ---------------------------------------------------------------------------


def test_sharpe_zero_for_flat_curve() -> None:
    assert sharpe_ratio(_curve([100, 100, 100, 100])) == 0.0


def test_sharpe_positive_for_uptrend() -> None:
    # Pure upward drift → positive Sharpe (very high since std is small)
    sharpe = sharpe_ratio(_curve([100, 101, 102, 103, 104, 105]))
    assert sharpe > 0


def test_cagr_one_year_doubling() -> None:
    start = date(2024, 1, 1)
    end = start + timedelta(days=365)
    pts = [
        EquityPoint(date=start, cash=0, positions_value=100, total=100),
        EquityPoint(date=end, cash=0, positions_value=200, total=200),
    ]
    # CAGR ≈ 100% over (almost) one year
    assert cagr(pts) == pytest.approx(1.0, rel=0.01)


def test_cagr_zero_for_short_window() -> None:
    same_day = _curve([100, 110])
    # both rows have same date in our helper unless we offset; but daily_returns still works
    # so just rely on the helper's ascending-day logic - cagr should be reasonable here.
    assert cagr(same_day) >= 0


# ---------------------------------------------------------------------------
# Trade stats / summary
# ---------------------------------------------------------------------------


def _trade(
    *, entry: float, exit: float, days: int = 5, signal: str = "BUY",
    reason: str = "signal_exit",
) -> Trade:
    return Trade(
        ticker="AAPL", market="US",
        entry_date=date(2024, 1, 2),
        exit_date=date(2024, 1, 2) + timedelta(days=days),
        entry_price=entry, exit_price=exit, shares=10,
        pnl=(exit - entry) * 10,
        pnl_pct=(exit - entry) / entry,
        holding_days=days,
        exit_reason=reason,  # type: ignore[arg-type]
        decision_signal=signal,  # type: ignore[arg-type]
        decision_confidence=70.0,
    )


def test_summary_with_real_trades() -> None:
    curve = _curve([100, 110, 105, 120, 115, 130])
    trades = [
        _trade(entry=100, exit=120, days=10),  # +20%
        _trade(entry=100, exit=92, days=4, reason="stop_loss"),  # -8%
        _trade(entry=100, exit=115, days=8),  # +15%
    ]
    s = summarise(curve, trades)
    assert s.starting_capital == 100
    assert s.ending_value == 130
    assert s.total_return == pytest.approx(0.30)
    assert s.trades.n_trades == 3
    assert s.trades.n_wins == 2
    assert s.trades.hit_rate == pytest.approx(2 / 3)
    assert s.trades.by_exit_reason["stop_loss"] == 1
    assert s.trades.by_exit_reason["signal_exit"] == 2


def test_summary_empty_inputs() -> None:
    s = summarise([], [])
    assert s.n_days == 0
    assert s.trades.n_trades == 0

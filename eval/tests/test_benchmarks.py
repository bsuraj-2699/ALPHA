"""Tests for benchmark equity-curve generation."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from eval.benchmarks import equal_weight_buy_and_hold, index_buy_and_hold


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_equal_weight_basket_starts_at_capital() -> None:
    start = date(2024, 1, 2)
    closes = {
        "A": _series(start, [100, 110]),
        "B": _series(start, [50, 50]),
    }
    result = equal_weight_buy_and_hold(["A", "B"], closes, starting_capital=10_000)
    assert result.equity_curve
    # First day total ≈ starting_capital (cash + positions)
    assert result.equity_curve[0].total == pytest.approx(10_000, rel=0.01)
    # Day 2: A goes 100 -> 110 (+10%), B flat. Half the basket up 10% => +5% total
    assert result.equity_curve[1].total > result.equity_curve[0].total


def test_equal_weight_skips_when_no_common_day() -> None:
    closes = {
        "A": {date(2024, 1, 1): 100.0},
        "B": {date(2024, 1, 5): 50.0},
    }
    result = equal_weight_buy_and_hold(["A", "B"], closes)
    assert not result.equity_curve
    assert "common" in result.notes.lower()


def test_index_buy_and_hold_grows_with_index() -> None:
    start = date(2024, 1, 2)
    closes = _series(start, [100.0, 105.0, 110.0])
    r = index_buy_and_hold("IN", closes, starting_capital=1000)
    assert r.equity_curve[0].total == pytest.approx(1000, abs=10)
    assert r.equity_curve[-1].total > r.equity_curve[0].total


def test_index_buy_and_hold_handles_empty() -> None:
    r = index_buy_and_hold("IN", {})
    assert not r.equity_curve

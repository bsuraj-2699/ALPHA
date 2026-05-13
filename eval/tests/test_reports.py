"""Unit tests for the HTML report renderer.

We only check structural invariants (well-formed HTML, expected
sections present) - rendering pixel-perfect output is not the point,
graceful handling of edge cases is.
"""

from __future__ import annotations

from datetime import date, timedelta

from eval.benchmarks import BenchmarkResult
from eval.metrics import summarise
from eval.portfolio import EquityPoint
from eval.reports import render_html
from eval.runner import BacktestConfig, BacktestResult, BacktestSpec


def _make_curve(values: list[float]) -> list[EquityPoint]:
    start = date(2024, 1, 2)
    return [
        EquityPoint(date=start + timedelta(days=i), cash=0, positions_value=v, total=v)
        for i, v in enumerate(values)
    ]


def test_render_html_includes_expected_sections() -> None:
    curve = _make_curve([100, 110, 105, 120, 130])
    spec = BacktestSpec("AAPL", "US", date(2024, 1, 2), date(2024, 1, 6))
    result = BacktestResult(
        config=BacktestConfig(),
        specs=[spec],
        equity_curve=curve,
        trades=[],
        decision_log=[],
        summary=summarise(curve, []),
        benchmark_basket=BenchmarkResult(name="basket", equity_curve=_make_curve([100, 102, 101, 105, 108])),
        benchmark_index=BenchmarkResult(name="index_NIFTYBEES", equity_curve=_make_curve([100, 101, 100, 102, 103])),
        decisions_emitted=2,
    )
    html = render_html(result)  # default title includes ticker
    assert "<!doctype html>" in html
    assert "Performance" in html
    assert "Equity curve" in html
    assert "Decision log" in html
    assert "<svg" in html
    assert "Strategy" in html
    assert "AAPL" in html


def test_render_html_handles_empty_result() -> None:
    spec = BacktestSpec("AAPL", "US", date(2024, 1, 2), date(2024, 1, 6))
    result = BacktestResult(config=BacktestConfig(), specs=[spec])
    html = render_html(result)
    # Nothing crashes; section headers still render.
    assert "<svg" in html
    assert "No decisions emitted" in html

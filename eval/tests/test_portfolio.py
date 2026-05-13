"""Pure-logic unit tests for ``PortfolioSimulator``.

No orchestrator, no yfinance, no async. Just feed a stream of bars +
decisions through the simulator and assert on cash / positions / trades.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from eval.portfolio import PortfolioSimulator
from packages.shared.schemas import Decision


def _decision(
    *,
    ticker: str = "AAPL",
    signal: str = "BUY",
    confidence: float = 70.0,
    position_size_pct: float = 5.0,
    entry_price: float | None = 100.0,
    stop_loss: float | None = 92.0,
    target_price: float | None = 120.0,
) -> Decision:
    return Decision(
        ticker=ticker,
        market="US",
        signal=signal,  # type: ignore[arg-type]
        confidence=confidence,
        position_size_pct=position_size_pct,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_price=target_price,
        rationale="unit test",
        citations=[],
        overrides_active=[],
        requires_human_review=False,
        timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )


def _bar(o: float, h: float, low: float, c: float) -> dict[str, float]:
    return {"open": o, "high": h, "low": low, "close": c}


# ---------------------------------------------------------------------------
# Sizing & cash flow
# ---------------------------------------------------------------------------


def test_buy_decision_opens_position_and_decrements_cash() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    today = date(2024, 1, 2)

    sim.mark_to_market(today, {})  # no positions yet
    sim.on_decision(today, "AAPL", "US", _decision(entry_price=100.0), current_price=100.0)

    pos = sim.positions["AAPL"]
    expected_shares = 50  # floor(100_000 * 0.05 / 100) == 50
    assert pos.shares == expected_shares
    assert sim.cash == pytest.approx(100_000 - 50 * 100)
    assert pos.stop_loss == 92.0


def test_decision_uses_current_price_when_entry_price_missing() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    sim.on_decision(
        date(2024, 1, 2),
        "AAPL",
        "US",
        _decision(entry_price=None),
        current_price=80.0,
    )
    assert sim.positions["AAPL"].entry_price == 80.0


def test_buy_skipped_when_already_open() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d = date(2024, 1, 2)
    sim.on_decision(d, "AAPL", "US", _decision(), current_price=100.0)
    cash_after_first = sim.cash
    sim.on_decision(d, "AAPL", "US", _decision(), current_price=100.0)
    assert sim.cash == cash_after_first
    assert sim.decision_log[-1].action_taken == "skipped_already_open"


# ---------------------------------------------------------------------------
# Stop-loss / target
# ---------------------------------------------------------------------------


def test_stop_loss_triggers_when_low_breaches_level() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d0 = date(2024, 1, 2)
    sim.on_decision(d0, "AAPL", "US", _decision(stop_loss=92.0), current_price=100.0)
    # Day 1: closed flat
    sim.mark_to_market(d0 + timedelta(days=1), {"AAPL": _bar(100, 101, 99, 100)})
    # Day 2: gaps down through stop
    sim.mark_to_market(d0 + timedelta(days=2), {"AAPL": _bar(95, 96, 90, 91)})

    assert "AAPL" not in sim.positions
    assert len(sim.trades) == 1
    t = sim.trades[0]
    assert t.exit_price == 92.0
    assert t.exit_reason == "stop_loss"
    assert t.pnl_pct == pytest.approx((92.0 - 100.0) / 100.0)


def test_target_triggers_when_high_meets_level() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d0 = date(2024, 1, 2)
    sim.on_decision(d0, "AAPL", "US", _decision(target_price=120.0), current_price=100.0)
    sim.mark_to_market(d0 + timedelta(days=1), {"AAPL": _bar(118, 121, 117, 119)})

    assert "AAPL" not in sim.positions
    assert sim.trades[0].exit_reason == "target"
    assert sim.trades[0].exit_price == 120.0


def test_stop_resolves_first_when_both_in_range() -> None:
    """Conservative convention: if both stop and target fall within the
    day's range, assume the stop hit first."""
    sim = PortfolioSimulator(starting_capital=100_000)
    d0 = date(2024, 1, 2)
    sim.on_decision(
        d0,
        "AAPL",
        "US",
        _decision(stop_loss=92.0, target_price=120.0),
        current_price=100.0,
    )
    # Wide-range day: low 91 (stop hit), high 121 (target hit)
    sim.mark_to_market(d0 + timedelta(days=1), {"AAPL": _bar(100, 121, 91, 110)})

    assert sim.trades[0].exit_reason == "stop_loss"


# ---------------------------------------------------------------------------
# Sell signal
# ---------------------------------------------------------------------------


def test_sell_signal_closes_existing_position() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d0 = date(2024, 1, 2)
    sim.on_decision(d0, "AAPL", "US", _decision(), current_price=100.0)
    sim.on_decision(
        d0 + timedelta(days=5),
        "AAPL",
        "US",
        _decision(signal="SELL"),
        current_price=110.0,
    )

    assert "AAPL" not in sim.positions
    assert sim.trades[0].exit_price == 110.0
    assert sim.trades[0].exit_reason == "signal_exit"


def test_sell_signal_with_no_position_is_a_noop() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    sim.on_decision(
        date(2024, 1, 2),
        "AAPL",
        "US",
        _decision(signal="SELL"),
        current_price=100.0,
    )
    assert not sim.trades
    assert not sim.positions
    assert sim.decision_log[-1].action_taken == "skipped_no_position"


# ---------------------------------------------------------------------------
# Multi-ticker + finalisation
# ---------------------------------------------------------------------------


def test_multi_ticker_independent_positions() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d = date(2024, 1, 2)
    sim.on_decision(
        d, "AAPL", "US", _decision(ticker="AAPL"), current_price=100.0,
    )
    sim.on_decision(
        d, "MSFT", "US", _decision(ticker="MSFT", entry_price=200.0, stop_loss=184.0),
        current_price=200.0,
    )
    assert {p for p in sim.positions} == {"AAPL", "MSFT"}


def test_close_remaining_marks_all_open_positions_at_final_close() -> None:
    sim = PortfolioSimulator(starting_capital=100_000)
    d0 = date(2024, 1, 2)
    sim.on_decision(d0, "AAPL", "US", _decision(), current_price=100.0)
    sim.close_remaining(d0 + timedelta(days=10), {"AAPL": _bar(105, 106, 103, 105)})

    assert "AAPL" not in sim.positions
    t = sim.trades[0]
    assert t.exit_price == 105.0
    assert t.exit_reason == "end_of_test"
    assert t.holding_days == 10


def test_skipped_when_cash_insufficient_for_a_share() -> None:
    sim = PortfolioSimulator(starting_capital=10.0)
    sim.on_decision(
        date(2024, 1, 2),
        "AAPL",
        "US",
        _decision(entry_price=100.0, position_size_pct=5.0),
        current_price=100.0,
    )
    assert not sim.positions
    assert sim.decision_log[-1].action_taken == "skipped_no_cash"

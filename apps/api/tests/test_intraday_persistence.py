"""Selective Postgres persistence for intraday vs longer horizons."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from apps.api.db import InMemoryRunLogStore
from apps.api.runs import RunManager, RunRecord


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_intraday_hold_writes_run_logs_not_intraday_signals() -> None:
    store = InMemoryRunLogStore()
    mgr = RunManager(MagicMock(), MagicMock(), store)
    rec = RunRecord(
        run_id="run-hold",
        ticker="AAPL",
        market="US",
        status="pending",
        created_at=_utc_now(),
        mode="intraday",
    )
    state = {
        "decision": {
            "signal": "HOLD",
            "confidence": 52.0,
            "timestamp": "2026-04-29T12:00:00+00:00",
            "data_coverage_pct": 80.0,
        },
        "judgment": {"composite_score": 52.0},
    }
    await mgr._handle_terminal(rec, state)

    assert "run-hold" in store._rows
    assert store._rows["run-hold"].final_signal == "HOLD"
    assert store._intraday_signals == {}


@pytest.mark.asyncio
async def test_intraday_buy_writes_run_log_and_intraday_row() -> None:
    store = InMemoryRunLogStore()
    mgr = RunManager(MagicMock(), MagicMock(), store)
    rec = RunRecord(
        run_id="run-buy",
        ticker="MSFT",
        market="US",
        status="pending",
        created_at=_utc_now(),
        mode="intraday",
    )
    state = {
        "decision": {
            "signal": "BUY",
            "confidence": 71.0,
            "timestamp": "2026-04-29T14:30:00+00:00",
            "data_coverage_pct": 90.0,
            "entry_price": 410.25,
            "stop_loss": 400.0,
            "target_price": 440.0,
        },
        "judgment": {"composite_score": 71.5},
    }
    await mgr._handle_terminal(rec, state)

    assert "run-buy" in store._rows
    assert store._rows["run-buy"].final_signal == "BUY"
    row = store._intraday_signals.get("run-buy")
    assert row is not None
    assert row.ticker == "MSFT"
    assert row.signal == "BUY"
    assert row.composite_score == 71.5
    assert row.confidence == 71.0
    assert row.primary_interval == "5minute"


@pytest.mark.asyncio
async def test_short_term_hold_still_writes_run_logs() -> None:
    store = InMemoryRunLogStore()
    mgr = RunManager(MagicMock(), MagicMock(), store)
    rec = RunRecord(
        run_id="run-st-hold",
        ticker="GOOG",
        market="US",
        status="pending",
        created_at=_utc_now(),
        mode="short_term",
    )
    state = {
        "decision": {
            "signal": "HOLD",
            "confidence": 48.0,
            "timestamp": "2026-04-29T16:00:00+00:00",
        },
        "judgment": {"composite_score": 48.0},
    }
    await mgr._handle_terminal(rec, state)

    assert store._intraday_signals == {}
    assert store._rows["run-st-hold"].final_signal == "HOLD"


@pytest.mark.asyncio
async def test_intraday_error_still_writes_run_logs() -> None:
    """Operational failures always reach ``run_logs`` — ops dashboards matter."""
    store = InMemoryRunLogStore()
    mgr = RunManager(MagicMock(), MagicMock(), store)
    rec = RunRecord(
        run_id="run-err",
        ticker="X",
        market="US",
        status="pending",
        created_at=_utc_now(),
        mode="intraday",
    )
    rec.completed_at = _utc_now()
    rec.error = "boom"
    rec.status = "error"
    await mgr._log_terminal(rec)

    assert store._rows["run-err"].status == "error"
    assert store._intraday_signals == {}

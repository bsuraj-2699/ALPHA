"""RunManager two-stage execution tests (Phase 11), offline.

Verifies at the RunManager layer (no FastAPI/httpx/DB) that:
  * the ``decision`` event is emitted during stage 1 (fast path);
  * ``decision_ready`` (TTD milestone) is published before ``analysis_complete``
    (enrichment) — i.e. narration does not block the decision;
  * a STRONG signal with auto-approve OFF interrupts for human review, and
    ``approve`` / reject finalize deterministically without a graph replay.
"""

from __future__ import annotations

import asyncio

import pytest

from apps.api.db import InMemoryRunLogStore
from apps.api.runs import RunManager
from packages.agents.llm_provider import llm_env_stripped_offline
from packages.agents.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def _force_offline():
    """Enrichment narration falls back to templated prose — no live LLM.

    (Enrichment is off the critical path, so its real-model latency never
    affects TTD; we strip keys here only to keep the unit test fast and
    deterministic.)"""
    with llm_env_stripped_offline():
        yield


class _StubBuilder:
    """Returns a fixed context, isolating the run from network I/O."""

    def __init__(self, ctx: dict) -> None:
        self._ctx = ctx

    async def build(self, ticker: str, market: str) -> dict:
        return dict(self._ctx)


class _RecordingBus:
    """Minimal EventBus double that records (run_id, event, payload)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    async def publish(self, run_id: str, event: str, payload: dict) -> None:
        self.events.append((run_id, event, payload))

    def types(self) -> list[str]:
        return [e for _rid, e, _p in self.events]


async def _drain(rec) -> None:
    if rec.task is not None:
        await rec.task


@pytest.fixture
def log_store() -> InMemoryRunLogStore:
    return InMemoryRunLogStore()


async def test_decision_emitted_before_enrichment(healthy_context, log_store) -> None:
    orch = Orchestrator(
        context_builder=_StubBuilder(healthy_context),
        auto_approve_strong_signals=True,
    )
    bus = _RecordingBus()
    mgr = RunManager(orch, bus, log_store)

    rec = await mgr.start_run("run-1", "GOODCO", "IN", mode="long_term")
    await _drain(rec)

    types = bus.types()
    assert "decision" in types
    assert "decision_ready" in types
    # TTD milestone precedes narration completion.
    assert types.index("decision_ready") < types.index("analysis_complete")
    assert rec.status == "complete"
    assert rec.state["decision"]["signal"] in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL")
    assert rec.ttd_ms is not None

    # After enrichment the per-pillar analyst reports (each with its own
    # confidence) must be present in the response — regression guard for the
    # two-stage flow dropping agent confidences.
    reports = rec.state.get("analyst_reports") or {}
    assert reports, "analyst_reports missing after enrichment"
    assert any("confidence" in r for r in reports.values())


async def test_fast_decision_matches_graph(fraudco_context, log_store) -> None:
    orch = Orchestrator(
        context_builder=_StubBuilder(fraudco_context),
        auto_approve_strong_signals=True,
    )
    graph = await orch.arun("Analyze FRAUDCO", ticker="FRAUDCO", market="IN")
    bus = _RecordingBus()
    mgr = RunManager(orch, bus, log_store)
    rec = await mgr.start_run("run-2", "FRAUDCO", "IN", mode="long_term")
    await _drain(rec)
    assert rec.state["decision"]["signal"] == graph["decision"].signal


async def test_strong_signal_interrupts_and_approves(fraudco_context, log_store) -> None:
    # FRAUDCO -> OVR-O1 -> STRONG_SELL; auto-approve OFF forces human review.
    orch = Orchestrator(
        context_builder=_StubBuilder(fraudco_context),
        auto_approve_strong_signals=False,
    )
    bus = _RecordingBus()
    mgr = RunManager(orch, bus, log_store)

    rec = await mgr.start_run("run-3", "FRAUDCO", "IN", mode="long_term")
    await _drain(rec)
    assert rec.status == "interrupted"
    assert rec.interrupt["signal"] == "STRONG_SELL"
    assert "decision" in bus.types()          # decision still emitted at TTD

    rec = await mgr.approve("run-3", "approve")
    await _drain(rec)
    assert rec.status == "complete"
    assert rec.state["decision"]["signal"] == "STRONG_SELL"


async def test_reject_downgrades_to_hold(fraudco_context, log_store) -> None:
    orch = Orchestrator(
        context_builder=_StubBuilder(fraudco_context),
        auto_approve_strong_signals=False,
    )
    bus = _RecordingBus()
    mgr = RunManager(orch, bus, log_store)
    rec = await mgr.start_run("run-4", "FRAUDCO", "IN", mode="long_term")
    await _drain(rec)
    rec = await mgr.approve("run-4", "no thanks")
    await _drain(rec)
    assert rec.status == "complete"
    assert rec.state["decision"]["signal"] == "HOLD"
    assert rec.state["decision"]["position_size_pct"] == 0.0

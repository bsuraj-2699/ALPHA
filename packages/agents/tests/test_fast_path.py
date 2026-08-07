"""Two-stage critical-path tests (Phase 11).

Guarantees under test:
  * ``arun_fast`` produces the SAME deterministic signal as the full graph
    (``arun``) — the split does not change what we trade.
  * ``arun_fast`` is reproducible (same inputs -> same signal + confidence).
  * ``arun_enrich`` (background narration) NEVER changes the signal, size, or
    confidence — it only fills in the rationale.
  * ``FastDecision.rule_summary`` exposes matched / skipped rules for the
    immediate response.

All offline: a StubContextBuilder supplies context, narrators fall back to
templated prose (no LLM key required).
"""

from __future__ import annotations

from packages.agents.orchestrator import Orchestrator


async def test_fast_signal_matches_graph(stub_builder_factory, fraudco_context) -> None:
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=True,
    )
    graph_state = await orch.arun("Analyze FRAUDCO", ticker="FRAUDCO", market="IN")
    fast = await orch.arun_fast(ticker="FRAUDCO", market="IN")

    assert fast.decision.signal == graph_state["decision"].signal
    assert fast.decision.signal == "STRONG_SELL"        # OVR-O1 fires
    assert "OVR-O1" in fast.decision.overrides_active
    assert fast.decision.position_size_pct == 0.0


async def test_fast_is_reproducible(stub_builder_factory, healthy_context) -> None:
    orch = Orchestrator(context_builder=stub_builder_factory(healthy_context))
    a = await orch.arun_fast(ticker="GOODCO", market="IN")
    b = await orch.arun_fast(ticker="GOODCO", market="IN")
    assert a.decision.signal == b.decision.signal
    assert a.decision.confidence == b.decision.confidence
    assert a.decision.composite_score == b.decision.composite_score


async def test_enrichment_never_changes_the_trade(stub_builder_factory, healthy_context) -> None:
    orch = Orchestrator(context_builder=stub_builder_factory(healthy_context))
    fast = await orch.arun_fast(ticker="GOODCO", market="IN")
    enriched = await orch.arun_enrich(fast)

    d0, d1 = fast.decision, enriched["decision"]
    assert d1.signal == d0.signal
    assert d1.confidence == d0.confidence
    assert d1.position_size_pct == d0.position_size_pct
    assert d1.entry_price == d0.entry_price
    # Only the prose may differ.
    assert isinstance(d1.rationale, str) and d1.rationale


async def test_fast_exposes_rule_summary_and_breakdown(stub_builder_factory, healthy_context) -> None:
    orch = Orchestrator(context_builder=stub_builder_factory(healthy_context))
    fast = await orch.arun_fast(ticker="GOODCO", market="IN")
    rs = fast.rule_summary()
    assert set(rs) == {"matched", "neutral", "skipped"}
    # Deterministic decision carries an auditable confidence breakdown.
    assert fast.decision.confidence_breakdown
    assert "evidence_quality" in fast.decision.confidence_breakdown

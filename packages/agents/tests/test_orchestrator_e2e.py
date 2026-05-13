"""End-to-end orchestrator tests.

Three flavors:
  * Synthetic FRAUDCO (fast)        - asserts override fast-path forces
                                      STRONG_SELL regardless of fundamentals.
  * Human-in-the-loop interrupt     - exercises LangGraph's interrupt() +
                                      Orchestrator.aresume() with both
                                      "approve" and "reject" responses.
  * Live AAPL / RELIANCE.NS         - hits yfinance over the network; marked
                                      pytest.mark.integration so they're
                                      skipped in default runs.

The synthetic and interrupt tests use a ``StubContextBuilder`` so they
don't depend on Anthropic keys, Qdrant, or yfinance.
"""

from __future__ import annotations

import os

import pytest

from packages.agents.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Synthetic FRAUDCO scenario
# ---------------------------------------------------------------------------


async def test_fraudco_strong_sell_overrides_score(stub_builder_factory, fraudco_context) -> None:
    """A fraud allegation triggers OVR-O1 (FORCE_STRONG_SELL); the deterministic
    signal MUST be STRONG_SELL, position size 0, even though every other pillar
    of the context is bullish.
    """
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=True,  # don't pause on STRONG_*
    )
    state = await orch.arun("Analyze FRAUDCO")

    decision = state.get("decision")
    assert decision is not None, "decide node failed to emit a Decision"

    # Override-driven outcome
    assert decision.signal == "STRONG_SELL", (
        f"FRAUDCO with has_fraud_allegation=True must force STRONG_SELL; "
        f"got {decision.signal} at confidence {decision.confidence}"
    )
    assert "OVR-O1" in decision.overrides_active, (
        f"OVR-O1 (fraud override) not surfaced in overrides_active: "
        f"{decision.overrides_active}"
    )

    # Position-size derivation must zero out on STRONG_SELL
    assert decision.position_size_pct == 0.0
    assert decision.entry_price is None
    assert decision.stop_loss is None
    assert decision.target_price is None

    # Human-review flag should be set on STRONG_*
    assert decision.requires_human_review is True

    # Confidence is the post-override composite score
    assert 0.0 <= decision.confidence <= 100.0


async def test_fraudco_judgment_overrides_dominate(stub_builder_factory, fraudco_context) -> None:
    """The Judgment object should record OVR-O1 in overrides_active and the
    narrative should mention the override (templated synthesis path)."""
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=True,
    )
    state = await orch.arun("Analyze FRAUDCO")

    judgment = state.get("judgment")
    assert judgment is not None
    assert judgment.signal == "STRONG_SELL"
    assert "OVR-O1" in judgment.overrides_active
    # Templated override synthesis should mention the override id explicitly.
    assert "OVR-O1" in judgment.narrative


async def test_healthy_context_buy_leaning(stub_builder_factory, healthy_context) -> None:
    """Sanity check: with no overrides triggered, the bullish-leaning context
    should produce a non-STRONG_SELL signal — confirms the FRAUDCO test isn't
    trivially passing because the context itself is bearish."""
    orch = Orchestrator(
        context_builder=stub_builder_factory(healthy_context),
        auto_approve_strong_signals=True,
    )
    state = await orch.arun("Analyze HEALTHCO")
    decision = state["decision"]

    assert decision.signal in ("STRONG_BUY", "BUY", "HOLD"), (
        f"healthy_context produced {decision.signal} - the FRAUDCO test is "
        f"only meaningful if the same context, sans fraud flag, leans bullish"
    )
    # No overrides should have triggered
    assert "OVR-O1" not in decision.overrides_active


# ---------------------------------------------------------------------------
# Human-in-the-loop interrupt
# ---------------------------------------------------------------------------


async def test_strong_signal_interrupts_when_auto_approve_disabled(
    stub_builder_factory, fraudco_context
) -> None:
    """With auto_approve_strong_signals=False, the decide node calls
    LangGraph's interrupt() for STRONG_*. The first ainvoke returns without a
    finalized decision; ``__interrupt__`` is present on the returned state."""
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=False,
    )
    state = await orch.arun("Analyze FRAUDCO")

    # LangGraph signals pending interrupts via the special __interrupt__ key.
    # Decision should NOT be finalized yet.
    assert "__interrupt__" in state, (
        "Expected __interrupt__ in state when auto_approve_strong_signals=False "
        "and signal is STRONG_*"
    )
    assert state.get("decision") is None, (
        "Decision should remain None until human reviewer resumes the graph"
    )


async def test_interrupt_resume_approve_finalizes_strong_sell(
    stub_builder_factory, fraudco_context
) -> None:
    """Resume with response='approve' -> the STRONG_SELL decision is kept."""
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=False,
    )
    paused = await orch.arun("Analyze FRAUDCO")
    thread_id = paused["_thread_id"]

    final = await orch.aresume(thread_id, "approve")
    decision = final.get("decision")
    assert decision is not None
    assert decision.signal == "STRONG_SELL"
    assert decision.position_size_pct == 0.0
    assert "OVR-O1" in decision.overrides_active


async def test_interrupt_resume_reject_downgrades_to_hold(
    stub_builder_factory, fraudco_context
) -> None:
    """Resume with anything other than 'approve' -> downgrade to HOLD."""
    orch = Orchestrator(
        context_builder=stub_builder_factory(fraudco_context),
        auto_approve_strong_signals=False,
    )
    paused = await orch.arun("Analyze FRAUDCO")
    thread_id = paused["_thread_id"]

    final = await orch.aresume(thread_id, "reject")
    decision = final.get("decision")
    assert decision is not None
    assert decision.signal == "HOLD"
    assert decision.position_size_pct == 0.0
    assert decision.requires_human_review is False
    # Original rationale should be preserved inside the new rationale.
    assert "rejected" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# Live integration tests (need yfinance / network access)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_aapl_e2e() -> None:
    """Full graph against AAPL via the real ContextBuilder. Asserts the
    pipeline produces a valid Decision; does NOT pin the signal because the
    market changes daily."""
    orch = Orchestrator(auto_approve_strong_signals=True)
    state = await orch.arun("Analyze AAPL")

    decision = state.get("decision")
    assert decision is not None
    assert decision.ticker == "AAPL"
    assert decision.market == "US"
    assert decision.signal in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL")
    assert 0.0 <= decision.confidence <= 100.0
    assert 0.0 <= decision.position_size_pct <= 10.0


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="NSE data via yfinance is flaky from CI runners",
)
async def test_reliance_e2e() -> None:
    """Full graph against RELIANCE.NS via the real ContextBuilder."""
    orch = Orchestrator(auto_approve_strong_signals=True)
    state = await orch.arun("Analyze RELIANCE.NS")

    decision = state.get("decision")
    assert decision is not None
    assert decision.ticker == "RELIANCE.NS"
    assert decision.market == "IN"
    assert decision.signal in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL")

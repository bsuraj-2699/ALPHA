"""Deterministic critical-path benchmark (offline, reproducible).

Phase 13 mandate: *never claim an optimization without measurement*. This
harness measures the **deterministic Time-To-Decision (TTD) critical path** —
the work that must finish before a BUY/SELL/HOLD can be emitted — in isolation
from LLM narration (which is being moved off the critical path) and from live
network I/O (stubbed here so the number is stable run-to-run).

What it measures
----------------
1. rule_eval          — RuleEvaluator.evaluate over a full context
2. confidence         — compute_confidence (7-axis)
3. memory_recall      — MarketMemoryRetriever.retrieve_evidence (in-memory)
4. decision_build     — DecisionAgent.build
5. ttd_critical_path  — Orchestrator.arun_fast end-to-end with a STUB context
                        builder (isolates deterministic compute from network)

Usage
-----
    uv run python scripts/benchmark.py                 # human table
    uv run python scripts/benchmark.py --json out.json # machine-readable
    uv run python scripts/benchmark.py --iters 2000    # tighter timing

The LLM narration path is intentionally NOT benchmarked here — it needs a live
model and its latency is provider-dependent. Its whole point post-refactor is
that it no longer blocks the decision, so it does not belong on the TTD path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_RULES = _ROOT / "packages" / "core" / "rules.json"


def _full_context() -> dict[str, Any]:
    """A realistic, well-covered intraday context so rules actually fire."""
    return {
        "market": "IN",
        "current_price": 118.0, "sma_50": 110.0, "sma_200": 100.0,
        "rsi_14": 64.0, "macd_histogram": 1.6, "adx": 30.0,
        "di_plus": 27.0, "di_minus": 13.0, "supertrend_direction": 1,
        "atr_pct": 1.3, "bb_percent_b": 0.72, "vwap": 115.0, "relative_volume": 1.8,
        "vix_level": 14.5, "vix_change_5d_pct": -1.5, "beta": 1.05,
        "stock_return_3m_pct": 14.0, "market_return_3m_pct": 6.0, "sector_return_3m_pct": 8.0,
        "market_regime": "bull", "nifty_trend": "uptrend",
        "pcr": 0.8, "iv": 19.0, "max_pain": 112.0, "oi_change_pct": 9.0,
        "fii_net_flow_cr": 2200.0, "dii_net_flow_cr": 700.0, "advance_decline_ratio": 1.5,
        "eps_yoy_pct": 22.0, "eps_qoq_pct": 6.0, "revenue_yoy_pct": 17.0,
        "net_margin_current": 18.0, "net_margin_2q_ago": 16.0, "roe_pct": 21.0,
        "roa_pct": 11.0, "fcf_yield_pct": 4.5, "debt_to_equity": 0.4,
        "current_ratio": 1.8, "interest_coverage_ratio": 9.0, "pe_ratio": 22.0,
        "forward_pe": 19.0, "peg_ratio": 1.1, "ev_ebitda": 14.0, "pb_ratio": 3.2,
        "dividend_yield_pct": 1.2, "sector": "technology",
        "fundamental_score": 68.0,
    }


def _time(label: str, fn: Callable[[], Any], iters: int) -> dict[str, Any]:
    fn()  # warm
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "label": label,
        "iters": iters,
        "mean_ms": round(statistics.mean(samples), 4),
        "p50_ms": round(samples[len(samples) // 2], 4),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 4),
        "max_ms": round(samples[-1], 4),
    }


async def _bench_ttd(iters: int) -> dict[str, Any]:
    """End-to-end deterministic TTD via arun_fast with a stub context builder."""
    from packages.agents.orchestrator import Orchestrator
    from packages.rag.market_memory import (
        MarketMemory,
        MarketMemoryRetriever,
        MarketMemoryStore,
    )

    ctx = _full_context()

    class _StubBuilder:
        async def build(self, ticker: str, market: str) -> dict[str, Any]:
            return dict(ctx)

    store = MarketMemoryStore(in_memory=True)
    for i in range(20):
        store.remember(
            MarketMemory(
                memory_id=f"seed-{i}", ticker="RELIANCE", timestamp="2026-01-05T10:00:00Z",
                timeframe="5minute", market_regime="bull", signal="BUY",
                composite_score=70, confidence=66,
                outcome="win" if i % 3 else "loss", pnl_pct=2.0 if i % 3 else -1.0,
            ),
            ctx,
        )
    orch = Orchestrator(
        context_builder=_StubBuilder(),
        market_memory=MarketMemoryRetriever(store),
    )

    async def once() -> Any:
        return await orch.arun_fast(ticker="RELIANCE", market="IN", mode="intraday")

    dec = await once()  # warm + sanity
    assert dec.decision.signal in ("STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL")
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        await once()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    return {
        "label": "ttd_critical_path (arun_fast, stub context)",
        "iters": iters,
        "mean_ms": round(statistics.mean(samples), 4),
        "p50_ms": round(samples[len(samples) // 2], 4),
        "p95_ms": round(samples[min(len(samples) - 1, int(len(samples) * 0.95))], 4),
        "max_ms": round(samples[-1], 4),
        "signal": dec.decision.signal,
        "confidence": dec.decision.confidence,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    from packages.core.confidence import compute_confidence
    from packages.core.rule_evaluator import RuleEvaluator
    from packages.rag.market_memory import (
        MarketMemory,
        MarketMemoryRetriever,
        MarketMemoryStore,
    )

    ctx = _full_context()
    ev_engine = RuleEvaluator(_RULES)
    evaluation = ev_engine.evaluate("RELIANCE", "IN", ctx, mode="intraday")

    store = MarketMemoryStore(in_memory=True)
    for i in range(20):
        store.remember(
            MarketMemory(
                memory_id=f"s{i}", ticker="RELIANCE", timestamp="t", timeframe="5minute",
                market_regime="bull", signal="BUY", composite_score=70, confidence=66,
                outcome="win" if i % 3 else "loss", pnl_pct=2.0 if i % 3 else -1.0,
            ),
            ctx,
        )
    retr = MarketMemoryRetriever(store)

    from packages.agents.decision import DecisionAgent
    from packages.shared.schemas import Judgment

    judgment = Judgment(
        signal=evaluation.final_signal_after_overrides,
        composite_score=evaluation.composite_score,
        overrides_active=[], narrative="x",
    )
    agent = DecisionAgent()

    results = [
        _time("rule_eval", lambda: ev_engine.evaluate("RELIANCE", "IN", ctx, mode="intraday"), args.iters),
        _time("confidence", lambda: compute_confidence(evaluation, ctx), args.iters),
        _time("memory_recall", lambda: retr.retrieve_evidence(ctx, "RELIANCE"), args.iters),
        _time("decision_build", lambda: agent.build("RELIANCE", "IN", judgment, ctx, evaluation=evaluation), args.iters),
    ]
    results.append(asyncio.run(_bench_ttd(max(50, args.iters // 5))))

    print(f"\nALPHA deterministic critical-path benchmark  (rules={_RULES.name})")
    print("-" * 78)
    print(f"{'stage':<44}{'p50 ms':>9}{'p95 ms':>9}{'mean ms':>10}")
    print("-" * 78)
    for r in results:
        print(f"{r['label']:<44}{r['p50_ms']:>9.3f}{r['p95_ms']:>9.3f}{r['mean_ms']:>10.3f}")
    print("-" * 78)
    ttd = results[-1]
    print(f"Deterministic TTD (compute only, network stubbed): "
          f"~{ttd['p95_ms']:.2f} ms p95  ->  signal={ttd.get('signal')} conf={ttd.get('confidence')}")
    print("Note: live TTD = this compute + market-data fetch (context build). LLM")
    print("narration is NOT on this path post-refactor.\n")

    if args.json:
        Path(args.json).write_text(json.dumps({"iters": args.iters, "results": results}, indent=2))
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

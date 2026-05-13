"""Scenario loader + runner.

A scenario is a JSON file with this shape::

    {
        "name": "Apple Q1 FY23 earnings beat",
        "description": "Strong YoY EPS, expanding margins, golden cross",
        "source": "Real event: Apple FY23 Q1 earnings, Feb 2 2023",
        "ticker": "AAPL",
        "market": "US",
        "context": { ... 80-ish RuleEvaluator fields ... },
        "expected_signal": "BUY",
        "expected_overrides": [],         // optional
        "expected_min_confidence": 60,    // optional, 0..100
        "expected_max_confidence": 100,   // optional, 0..100
        "notes": "..."
    }

Why JSON and not YAML? Stable diffs, no anchors, no surprises. The cost
is verbosity for the context dict; the benefit is that every CI failure
points exactly at the field that drifted.

Tolerances
----------
``expected_signal`` is a hard match. ``expected_overrides`` is checked
as a *subset* (the actual list may include lower-priority overrides we
didn't pin). Confidence bounds are optional and only enforced when
present.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from eval.historical_context import NoopBuilder
from packages.agents.llm_provider import llm_env_stripped_offline
from packages.agents.orchestrator import Orchestrator
from packages.shared.schemas import Decision, Market, Signal

SCENARIOS_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Spec / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    path: Path
    name: str
    description: str
    source: str
    ticker: str
    market: Market
    context: dict[str, Any]
    expected_signal: Signal
    expected_overrides: list[str] = field(default_factory=list)
    expected_min_confidence: float | None = None
    expected_max_confidence: float | None = None
    notes: str = ""


@dataclass
class ScenarioResult:
    scenario: Scenario
    decision: Decision | None
    passed: bool
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_scenario(path: Path) -> Scenario:
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = ("name", "ticker", "market", "context", "expected_signal")
    for k in required:
        if k not in raw:
            raise ValueError(f"{path.name}: missing required field {k!r}")

    market: Market = raw["market"].upper()
    if market not in ("US", "IN"):
        raise ValueError(f"{path.name}: market must be 'US' or 'IN', got {market!r}")

    expected_signal: Signal = raw["expected_signal"].upper()
    if expected_signal not in (
        "STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"
    ):
        raise ValueError(f"{path.name}: invalid expected_signal {expected_signal!r}")

    return Scenario(
        path=path,
        name=raw["name"],
        description=raw.get("description", ""),
        source=raw.get("source", ""),
        ticker=raw["ticker"],
        market=market,
        context=raw["context"],
        expected_signal=expected_signal,
        expected_overrides=list(raw.get("expected_overrides", [])),
        expected_min_confidence=raw.get("expected_min_confidence"),
        expected_max_confidence=raw.get("expected_max_confidence"),
        notes=raw.get("notes", ""),
    )


def discover_scenarios(directory: Path | None = None) -> list[Path]:
    """All ``*.json`` files in ``directory`` (default: ``eval/scenarios/``).

    Hidden / dot-prefixed files and ``schema.json`` (if any) are excluded
    so we can drop a JSON-Schema in the folder later without it being
    treated as a scenario.
    """
    directory = directory or SCENARIOS_DIR
    return sorted(
        p for p in directory.glob("*.json")
        if not p.name.startswith(("_", ".")) and p.name != "schema.json"
    )


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


@contextmanager
def _force_offline_llm() -> Iterator[None]:
    """Strip all known LLM API keys so templated narrators run.

    A scenario test is a behavioural pin on the *deterministic* part of
    the pipeline (rule evaluator, signal mapping, override application,
    decision sizing). LLM narrators don't change scores, so they're
    irrelevant to the assertion - we don't want to burn tokens or pull
    on the network just to assert a signal.
    """
    with llm_env_stripped_offline():
        yield


async def run_scenario(
    scenario: Scenario,
    orchestrator: Orchestrator | None = None,
) -> ScenarioResult:
    """Run one scenario through the full orchestrator and validate the result."""
    orch = orchestrator or Orchestrator(
        context_builder=NoopBuilder(),
        auto_approve_strong_signals=True,
    )

    with _force_offline_llm():
        try:
            state = await orch.arun(
                query=f"Analyze {scenario.ticker}",
                ticker=scenario.ticker,
                market=scenario.market,
                context_overrides=dict(scenario.context),
            )
        except Exception as e:  # pragma: no cover - defensive
            return ScenarioResult(
                scenario=scenario,
                decision=None,
                passed=False,
                failure_reason=f"orchestrator raised {type(e).__name__}: {e}",
            )

    decision: Any = state.get("decision") if isinstance(state, dict) else None
    if not isinstance(decision, Decision):
        # Could have been serialised by the checkpointer
        if isinstance(decision, dict):
            try:
                decision = Decision.model_validate(decision)
            except Exception as e:
                return ScenarioResult(
                    scenario=scenario,
                    decision=None,
                    passed=False,
                    failure_reason=f"could not validate Decision dict: {e}",
                )
        else:
            return ScenarioResult(
                scenario=scenario,
                decision=None,
                passed=False,
                failure_reason="orchestrator returned no Decision",
            )

    return _validate(scenario, decision)


def _validate(scenario: Scenario, decision: Decision) -> ScenarioResult:
    if decision.signal != scenario.expected_signal:
        return ScenarioResult(
            scenario=scenario,
            decision=decision,
            passed=False,
            failure_reason=(
                f"signal mismatch: expected {scenario.expected_signal}, "
                f"got {decision.signal} (confidence={decision.confidence:.1f}, "
                f"overrides={decision.overrides_active})"
            ),
        )

    actual_ovr = set(decision.overrides_active)
    expected_ovr = set(scenario.expected_overrides)
    missing = expected_ovr - actual_ovr
    if missing:
        return ScenarioResult(
            scenario=scenario,
            decision=decision,
            passed=False,
            failure_reason=(
                f"missing expected overrides: {sorted(missing)} "
                f"(actual={sorted(actual_ovr)})"
            ),
        )

    if scenario.expected_min_confidence is not None:
        if decision.confidence < scenario.expected_min_confidence:
            return ScenarioResult(
                scenario=scenario,
                decision=decision,
                passed=False,
                failure_reason=(
                    f"confidence {decision.confidence:.1f} < "
                    f"expected_min {scenario.expected_min_confidence}"
                ),
            )
    if scenario.expected_max_confidence is not None:
        if decision.confidence > scenario.expected_max_confidence:
            return ScenarioResult(
                scenario=scenario,
                decision=decision,
                passed=False,
                failure_reason=(
                    f"confidence {decision.confidence:.1f} > "
                    f"expected_max {scenario.expected_max_confidence}"
                ),
            )

    return ScenarioResult(scenario=scenario, decision=decision, passed=True)


__all__ = [
    "SCENARIOS_DIR",
    "Scenario",
    "ScenarioResult",
    "discover_scenarios",
    "load_scenario",
    "run_scenario",
]

"""CI gate: run every hand-labeled scenario through the full orchestrator
and assert the deterministic signal hasn't drifted.

A scenario fails if:
  * the signal differs from ``expected_signal``
  * any expected override didn't fire
  * confidence is outside the [min, max] bounds (when those are set)

This is the regression test for any change to:
  * ``packages/core/rules.json``
  * ``RuleEvaluator`` scoring / threshold logic
  * ``Judge`` override path
  * ``Decision`` agent's signal mapping

Run subset: ``pytest eval/tests/test_scenarios.py -k aapl``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.scenarios.runner import (
    discover_scenarios,
    load_scenario,
    run_scenario,
)


_ALL_PATHS = discover_scenarios()


@pytest.mark.parametrize(
    "scenario_path",
    _ALL_PATHS,
    ids=[p.stem for p in _ALL_PATHS],
)
async def test_scenario_signal_matches_expected(scenario_path: Path) -> None:
    scenario = load_scenario(scenario_path)
    result = await run_scenario(scenario)
    assert result.passed, (
        f"\nScenario: {scenario.name} ({scenario_path.name})"
        f"\nDescription: {scenario.description}"
        f"\nExpected signal: {scenario.expected_signal}"
        f"\nActual signal: "
        f"{result.decision.signal if result.decision else 'NO DECISION'}"
        f"\nReason: {result.failure_reason}"
    )


def test_at_least_one_scenario_per_signal_class() -> None:
    """The eval set should cover every signal we ship.

    If a future change adds a new signal value, this test will remind us
    to ship a scenario for it.
    """
    expected = {load_scenario(p).expected_signal for p in _ALL_PATHS}
    must_have = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}
    missing = must_have - expected
    assert not missing, f"Missing scenario coverage for signals: {sorted(missing)}"

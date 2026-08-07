"""Totality checks for rule condition ladders.

A rule whose tiers don't cover its whole input space has a dead zone: real data
arrives, no condition matches, and the rule abstains. Before these were closed,
14 of 36 rules abstained somewhere on the eval fixtures and the survivors
clustered the composite around 50, which is why nearly every run returned HOLD.

The evaluator still abstains as a safety net (and says so in the notes), but
these rules are meant to be total, so a regression should fail here first.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from packages.core.rule_evaluator import evaluate_condition

_RULES = Path(__file__).resolve().parents[1] / "rules.json"
_TIERS = ("strong_buy", "buy", "strong_sell", "sell", "neutral")

# Input spaces chosen to straddle every literal each ladder compares against,
# including the exact boundary values.
_SPACES = {
    "FUND-001": {
        "eps_yoy_pct": [-40.0, -25.0, -10.001, -10.0, -5.0, -0.001, 0.0, 3.0,
                        9.999, 10.0, 20.0, 50.0],
        "eps_qoq_pct": [-5.0, 0.0, 5.0],
        "eps_misses_consecutive": [0, 2, 3],
    },
    "FUND-002": {
        "revenue_yoy_pct": [-20.0, -15.0, -5.001, -5.0, -0.001, 0.0, 7.999,
                            8.0, 15.0, 40.0],
        "revenue_decline_quarters_consecutive": [0, 2, 3],
    },
    "MOM-003": {
        "stoch_k": [0.0, 15.0, 19.999, 25.0, 30.0, 50.0, 70.0, 70.001, 85.0, 100.0],
        "stoch_d": [0.0, 15.0, 25.0, 50.0, 70.0, 85.0, 100.0],
        "stoch_k_prev": [10.0, 50.0, 90.0],
        "stoch_d_prev": [10.0, 50.0, 90.0],
    },
    "MOM-006": {
        "current_price": [50.0, 98.0, 99.5, 100.0, 101.0, 105.0, 150.0],
        "nearest_support": [90.0, 100.0],
        "nearest_resistance": [100.0, 120.0],
        "bounced_off_support_today": [True, False],
        "broke_support_today": [True, False],
        "volume_today": [5e5, 2e6],
        "volume_avg_20d": [1e6],
    },
    "MACRO-004": {
        "stock_return_3m_pct": [-20.0, -5.0, 0.0, 5.0, 20.0],
        "sector_return_3m_pct": [-5.0, 0.0, 5.0],
        "market_return_3m_pct": [-5.0, 0.0, 5.0],
        "rs_line_at_3m_high": [True, False],
    },
    "RISK-001": {
        "beta": [-0.5, 0.0, 0.5, 0.8, 1.0, 1.2, 1.4999, 1.5, 2.0, 3.0],
        # Includes a regime outside the bull/bear vocabulary on purpose.
        "market_regime": ["bull", "bear", "neutral", "sideways"],
    },
}


def _conditions(rule_id):
    spec = json.loads(_RULES.read_text(encoding="utf-8"))
    return next(r for r in spec["rules"] if r["id"] == rule_id)["conditions"]


@pytest.mark.parametrize("rule_id", sorted(_SPACES))
def test_ladder_covers_its_input_space(rule_id):
    conds = _conditions(rule_id)
    space = _SPACES[rule_id]
    keys = list(space)
    holes = []
    for combo in itertools.product(*(space[k] for k in keys)):
        ctx = dict(zip(keys, combo))
        if not any(evaluate_condition(conds[t], ctx) for t in _TIERS if conds.get(t)):
            holes.append(ctx)
    assert not holes, f"{rule_id} has {len(holes)} dead zone(s), e.g. {holes[0]}"


def test_thresholds_are_contiguous_and_cover_zero_to_hundred():
    """A gap between bands would silently fall through to no signal at all."""
    spec = json.loads(_RULES.read_text(encoding="utf-8"))
    scopes = {"default": spec.get("thresholds") or []}
    for mode, cfg in spec.get("modes", {}).items():
        if cfg.get("thresholds"):
            scopes[mode] = cfg["thresholds"]

    for scope, bands in scopes.items():
        ordered = sorted(bands, key=lambda b: b["min"])
        assert ordered[0]["min"] == 0, f"{scope} does not start at 0"
        assert ordered[-1]["max"] == 100, f"{scope} does not end at 100"
        for lower, upper in zip(ordered, ordered[1:]):
            gap = round(upper["min"] - lower["max"], 6)
            assert gap == 0.01, (
                f"{scope}: {lower['signal']} ends at {lower['max']} but "
                f"{upper['signal']} starts at {upper['min']}"
            )

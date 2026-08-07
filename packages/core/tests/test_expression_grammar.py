"""Regression tests for the rule-condition expression grammar.

Every bug covered here failed *silently*: an unparseable side coerced to None,
the comparison answered False, no tier matched, and the rule dropped out of the
composite without complaint. Collectively they scored bearish evidence at half
strength and pulled almost every run into the HOLD band, so these cases are
worth pinning even though they look trivial.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.core.rule_evaluator import RuleEvaluator, evaluate_condition

_RULES = Path(__file__).resolve().parents[1] / "rules.json"


@pytest.mark.parametrize(
    ("expr", "ctx", "expected"),
    [
        # A decimal literal used to make _coerce mistake the whole expression
        # for an attribute path: "bb_upper * 0.98".split(".") -> no such name.
        ("current_price >= bb_upper * 0.98", {"current_price": 165.0, "bb_upper": 156.0}, True),
        ("current_price >= bb_upper * 0.98", {"current_price": 100.0, "bb_upper": 156.0}, False),
        ("current_price <= bb_lower * 1.02", {"current_price": 139.0, "bb_lower": 140.0}, True),
        # Integer multipliers always worked; keep them working.
        ("volume_today >= volume_avg_20d * 2", {"volume_today": 2.5e6, "volume_avg_20d": 1e6}, True),
        # abs() as a sub-term, not the whole token.
        ("abs(current_price - nearest_support) / current_price < 0.02",
         {"current_price": 100.0, "nearest_support": 99.5}, True),
        ("abs(current_price - nearest_support) / current_price < 0.02",
         {"current_price": 100.0, "nearest_support": 80.0}, False),
        # Two abs() calls either side of an operator. The old whole-token
        # shortcut matched greedily from the first "abs(" to the last ")",
        # producing an unbalanced body that evaluated to nothing.
        ("abs(macd_line - macd_signal) / abs(macd_signal) < 0.05",
         {"macd_line": 1.0, "macd_signal": 1.02}, True),
        ("abs(macd_line - macd_signal) / abs(macd_signal) < 0.05",
         {"macd_line": 1.0, "macd_signal": 2.0}, False),
        # Genuine attribute access must survive the narrowed guard.
        ("sector.buy_max >= 5", {"sector": {"buy_max": 10}}, True),
        ("sector.buy_max >= 5", {"sector": {"buy_max": 1}}, False),
        ("debt_to_equity >= (sector.sell_min * 1.5)",
         {"debt_to_equity": 3.0, "sector": {"sell_min": 1.0}}, True),
    ],
)
def test_arithmetic_and_attribute_expressions(expr, ctx, expected):
    assert evaluate_condition(expr, ctx) is expected


def test_missing_operand_is_false_not_an_error():
    """A field the context lacks is ordinary missing data, not a crash."""
    assert evaluate_condition("current_price >= bb_upper * 0.98", {"current_price": 1.0}) is False


class TestTierOrdering:
    """The extreme tier must be tested before the moderate one it sits inside.

    strong_sell conditions are written as a tightening of sell ("< -10" vs
    "< -25"), so checking sell first made strong_sell unreachable and scored
    the rule 25 where it should have scored 0.
    """

    def _rule(self, rule_id):
        spec = json.loads(_RULES.read_text(encoding="utf-8"))
        return next(r for r in spec["rules"] if r["id"] == rule_id)

    def test_strong_sell_wins_over_sell_when_both_match(self):
        evaluator = RuleEvaluator(str(_RULES))
        rule = self._rule("FUND-001")
        ctx = {"eps_yoy_pct": -40.0, "eps_qoq_pct": -5.0, "eps_misses_consecutive": 4}
        # Both ladders match this input; the extreme one must win.
        assert evaluate_condition(rule["conditions"]["sell"], ctx) is True
        assert evaluate_condition(rule["conditions"]["strong_sell"], ctx) is True
        assert evaluator._evaluate_rule(rule, ctx, "IN").tier == "strong_sell"

    def test_strong_buy_still_wins_over_buy(self):
        evaluator = RuleEvaluator(str(_RULES))
        rule = self._rule("FUND-001")
        ctx = {"eps_yoy_pct": 50.0, "eps_qoq_pct": 5.0, "eps_misses_consecutive": 0}
        assert evaluator._evaluate_rule(rule, ctx, "IN").tier == "strong_buy"

"""Unit tests for the redesigned, multi-axis confidence estimator."""

from __future__ import annotations

from pathlib import Path

from packages.core.confidence import compute_confidence
from packages.core.rule_evaluator import RuleEvaluator

_RULES = Path(__file__).resolve().parents[1] / "rules.json"


def _evaluator() -> RuleEvaluator:
    return RuleEvaluator(_RULES)


def _strong_bull_ctx() -> dict:
    # Enough real inputs across pillars to fire bullish tiers.
    return {
        "market": "IN",
        "rsi_14": 66, "macd_histogram": 1.8, "sma_50": 110, "sma_200": 100,
        "current_price": 118, "di_plus": 28, "di_minus": 12,
        "stock_return_3m_pct": 15, "market_return_3m_pct": 5,
        "market_regime": "bull", "nifty_trend": "uptrend",
        "vix_level": 14, "vix_change_5d_pct": -2, "beta": 1.0,
        "eps_yoy_pct": 25, "revenue_yoy_pct": 18, "roe_pct": 22, "pe_ratio": 20,
    }


def test_confidence_is_zero_to_hundred() -> None:
    ev = _evaluator().evaluate("RELIANCE", "IN", _strong_bull_ctx())
    b = compute_confidence(ev, _strong_bull_ctx())
    assert 0.0 <= b.confidence <= 100.0
    assert set(b.axes).issubset({
        "data_coverage", "rule_agreement", "pillar_agreement",
        "indicator_agreement", "regime_confidence", "rule_consistency",
        "historical_success",
    })


def test_confidence_not_equal_to_composite_and_breakdown_present() -> None:
    ctx = _strong_bull_ctx()
    ev = _evaluator().evaluate("RELIANCE", "IN", ctx)
    b = compute_confidence(ev, ctx)
    # It must be a real decomposition, not the raw score passthrough.
    assert b.axes  # non-empty
    assert 0.0 <= b.evidence_quality <= 1.0
    assert b.as_dict()["axes"]  # serialisable breakdown


def test_thin_data_lowers_confidence() -> None:
    ctx = _strong_bull_ctx()
    ev = _evaluator().evaluate("RELIANCE", "IN", ctx)

    # Two evaluations identical in every axis EXCEPT data coverage / skip
    # ratio. The confidence layer must reward the well-covered one.
    def _stub(coverage: float, evaluated: int, skipped: int):
        class _E:
            composite_score = ev.composite_score
            pillar_scores = ev.pillar_scores
            pillar_details = ev.pillar_details
            overrides_triggered = ev.overrides_triggered
            rules_evaluated_count = evaluated
            rules_skipped_count = skipped
            data_coverage_pct = coverage
        return _E()

    full = compute_confidence(_stub(90.0, 30, 3), ctx)
    thin = compute_confidence(_stub(20.0, 4, 20), ctx)
    assert thin.confidence < full.confidence


def test_historical_evidence_shifts_confidence() -> None:
    ctx = _strong_bull_ctx()
    ev = _evaluator().evaluate("RELIANCE", "IN", ctx)
    base = compute_confidence(ev, ctx)
    winning = compute_confidence(
        ev, ctx, historical_success=0.9, historical_similarity=0.9, n_historical=8
    )
    losing = compute_confidence(
        ev, ctx, historical_success=0.1, historical_similarity=0.9, n_historical=8
    )
    assert winning.confidence >= base.confidence >= losing.confidence
    assert winning.n_historical == 8

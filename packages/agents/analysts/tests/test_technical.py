"""Tests for TechnicalAnalyst.

Identical shape to test_fundamental.py + an extra ``test_blend_formula``
that pins the trend*0.625 + momentum*0.375 framework formula.
"""

from __future__ import annotations

import pytest

from packages.agents.analysts.technical import TechnicalAnalyst
from packages.agents.llm_provider import is_any_llm_configured
from packages.agents.analysts.tests.conftest import make_fake_narrator


def test_categories() -> None:
    assert TechnicalAnalyst.pillar == "technicals"
    assert TechnicalAnalyst.categories == ("trend", "momentum")


async def test_score_matches_evaluator(evaluator, rich_context) -> None:
    eval_ = evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, TechnicalAnalyst.categories
    )
    analyst = TechnicalAnalyst(evaluator, narrator=make_fake_narrator())
    expected_score = analyst.aggregate(eval_.per_category_scores, eval_)

    report = await analyst.analyze(rich_context, "AAPL", "US")

    assert report.pillar == "technicals"
    assert report.score == pytest.approx(expected_score)
    assert report.score != pytest.approx(50.0)


def test_blend_formula(evaluator, rich_context) -> None:
    """The technical analyst must use the framework's 0.625/0.375 weights,
    not the default mean. This is the only structural deviation from
    BaseAnalyst — it's worth pinning explicitly."""
    eval_ = evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, TechnicalAnalyst.categories
    )
    trend = eval_.per_category_scores.get("trend", 50.0)
    momentum = eval_.per_category_scores.get("momentum", 50.0)
    expected = trend * 0.625 + momentum * 0.375

    analyst = TechnicalAnalyst(evaluator)
    assert analyst.aggregate(eval_.per_category_scores, eval_) == pytest.approx(expected)


async def test_citations_sanitized(evaluator, rich_context) -> None:
    analyst = TechnicalAnalyst(
        evaluator,
        narrator=make_fake_narrator(
            top_signals=[
                "TREND-001: real",
                "FAKE-999: hallucinated",
            ],
            citations=["TREND-001", "FAKE-999"],
        ),
    )
    report = await analyst.analyze(rich_context, "AAPL", "US")
    assert "FAKE-999" not in report.citations
    assert not any(s.startswith("FAKE-999") for s in report.top_signals)


async def test_offline_fallback(evaluator, rich_context, strip_llm_keys) -> None:
    analyst = TechnicalAnalyst(evaluator)
    report = await analyst.analyze(rich_context, "AAPL", "US")
    assert report.narrative
    assert report.confidence > 0
    assert report.pillar == "technicals"


@pytest.mark.live
@pytest.mark.skipif(
    not is_any_llm_configured(),
    reason="live LLM tests require at least one LLM API key",
)
async def test_live_llm(evaluator, rich_context) -> None:
    analyst = TechnicalAnalyst(evaluator)
    report = await analyst.analyze(rich_context, "AAPL", "US")

    valid_ids = {r.rule_id for r in evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, TechnicalAnalyst.categories
    ).rule_results}
    assert report.narrative
    assert all(c in valid_ids for c in report.citations)

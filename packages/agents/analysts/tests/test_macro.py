"""Tests for MacroAnalyst. Same shape as test_fundamental.py."""

from __future__ import annotations

import pytest

from packages.agents.analysts.macro import MacroAnalyst
from packages.agents.llm_provider import is_any_llm_configured
from packages.agents.analysts.tests.conftest import make_fake_narrator


def test_categories() -> None:
    assert MacroAnalyst.pillar == "macro"
    assert MacroAnalyst.categories == ("macro",)


async def test_score_matches_evaluator(evaluator, rich_context) -> None:
    eval_ = evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, MacroAnalyst.categories
    )
    analyst = MacroAnalyst(evaluator, narrator=make_fake_narrator())
    expected_score = analyst.aggregate(eval_.per_category_scores, eval_)

    report = await analyst.analyze(rich_context, "AAPL", "US")

    assert report.pillar == "macro"
    assert report.score == pytest.approx(expected_score)


async def test_citations_sanitized(evaluator, rich_context) -> None:
    analyst = MacroAnalyst(
        evaluator,
        narrator=make_fake_narrator(
            top_signals=["MACRO-001: real", "FAKE-999: hallucinated"],
            citations=["MACRO-001", "FAKE-999"],
        ),
    )
    report = await analyst.analyze(rich_context, "AAPL", "US")
    assert "FAKE-999" not in report.citations
    assert not any(s.startswith("FAKE-999") for s in report.top_signals)


async def test_offline_fallback(evaluator, rich_context, strip_llm_keys) -> None:
    analyst = MacroAnalyst(evaluator)
    report = await analyst.analyze(rich_context, "AAPL", "US")
    assert report.narrative
    assert report.confidence > 0
    assert report.pillar == "macro"


@pytest.mark.live
@pytest.mark.skipif(
    not is_any_llm_configured(),
    reason="live LLM tests require at least one LLM API key",
)
async def test_live_llm(evaluator, rich_context) -> None:
    analyst = MacroAnalyst(evaluator)
    report = await analyst.analyze(rich_context, "AAPL", "US")
    valid_ids = {r.rule_id for r in evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, MacroAnalyst.categories
    ).rule_results}
    assert report.narrative
    assert all(c in valid_ids for c in report.citations)

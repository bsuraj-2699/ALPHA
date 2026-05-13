"""Tests for FundamentalAnalyst.

Same shape as every other analyst test file (see test_technical.py etc.):

    test_categories          - declared class attrs match the rule taxonomy
    test_score_matches_evaluator - the deterministic score flows through;
                                   the LLM cannot influence it
    test_citations_sanitized - hallucinated rule ids are stripped
    test_offline_fallback    - no API key, no narrator -> templated narrative
    test_live_llm            - marked 'live'; skipped without any LLM API key
"""

from __future__ import annotations

import pytest

from packages.agents.analysts.fundamental import FundamentalAnalyst
from packages.agents.llm_provider import is_any_llm_configured
from packages.agents.analysts.tests.conftest import make_fake_narrator


def test_categories() -> None:
    assert FundamentalAnalyst.pillar == "fundamentals"
    assert FundamentalAnalyst.categories == ("fundamentals", "balance_sheet")


async def test_score_matches_evaluator(evaluator, rich_context) -> None:
    eval_ = evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, FundamentalAnalyst.categories
    )
    analyst = FundamentalAnalyst(
        evaluator,
        narrator=make_fake_narrator(narrative="Will be ignored for score."),
    )
    expected_score = analyst.aggregate(eval_.per_category_scores, eval_)

    report = await analyst.analyze(rich_context, "AAPL", "US")

    assert report.pillar == "fundamentals"
    assert report.score == pytest.approx(expected_score)
    # Sanity check: rich context fires enough rules that the score is
    # non-default. Otherwise we wouldn't be testing anything useful.
    assert report.score != pytest.approx(50.0), (
        "rich_context must fire some fundamental rules; otherwise the test "
        "trivially passes against the neutral default"
    )


async def test_citations_sanitized(evaluator, rich_context) -> None:
    analyst = FundamentalAnalyst(
        evaluator,
        narrator=make_fake_narrator(
            top_signals=[
                "FUND-001: real signal",
                "FAKE-999: hallucinated rule id",
            ],
            citations=["FUND-001", "FAKE-999"],
        ),
    )
    report = await analyst.analyze(rich_context, "AAPL", "US")

    assert "FAKE-999" not in report.citations
    assert not any(s.startswith("FAKE-999") for s in report.top_signals)


async def test_offline_fallback(evaluator, rich_context, strip_llm_keys) -> None:

    analyst = FundamentalAnalyst(evaluator)  # no narrator -> default resolves offline
    report = await analyst.analyze(rich_context, "AAPL", "US")

    assert report.narrative
    assert report.confidence > 0
    assert report.pillar == "fundamentals"


@pytest.mark.live
@pytest.mark.skipif(
    not is_any_llm_configured(),
    reason="live LLM tests require at least one LLM API key",
)
async def test_live_llm(evaluator, rich_context) -> None:
    analyst = FundamentalAnalyst(evaluator)
    report = await analyst.analyze(rich_context, "AAPL", "US")

    valid_ids = {r.rule_id for r in evaluator.evaluate_pillar(
        "AAPL", "US", rich_context, FundamentalAnalyst.categories
    ).rule_results}
    assert report.narrative
    assert all(c in valid_ids for c in report.citations)

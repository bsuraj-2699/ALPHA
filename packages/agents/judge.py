"""Strategy Judge agent — instructor + LiteLLM (multi-provider)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from packages.core.rule_evaluator import EvaluationResult, OverrideResult, RuleEvaluator
from packages.shared.schemas import BearCase, BullCase, Judgment, JudgeNarrative, Market

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "judge.txt"

JudgeNarrator = Callable[[str, dict[str, Any]], Awaitable[JudgeNarrative]]
RAGRetriever  = Any


class Judge:
    def __init__(
        self,
        evaluator: RuleEvaluator,
        retriever: RAGRetriever | None = None,
        narrator:  JudgeNarrator | None = None,
        openai_model: str = "gpt-4o",
        max_tokens:   int = 1500,
        temperature:  float = 0.3,
        rag_top_k:    int = 5,
    ) -> None:
        self.evaluator    = evaluator
        self.retriever    = retriever
        self._narrator    = narrator
        self.openai_model = openai_model
        self.max_tokens   = max_tokens
        self.temperature  = temperature
        self.rag_top_k    = rag_top_k

    async def judge(
        self,
        ticker: str,
        market: Market,
        context: dict[str, Any],
        bull_case: BullCase | None,
        bear_case: BearCase | None,
        category_weights: dict[str, float] | None = None,
        mode: str | None = None,
    ) -> tuple[Judgment, EvaluationResult]:
        evaluation      = self.evaluator.evaluate(
            ticker, market, context,
            category_weights=category_weights,
            mode=mode,
        )
        active_overrides = [o for o in evaluation.overrides_triggered if o.triggered]
        active_override_ids = [o.override_id for o in active_overrides]

        score_overriding = [o for o in active_overrides if _is_score_overriding(o.action)]
        if score_overriding:
            return _templated_override_judgment(
                evaluation, score_overriding, bull_case, bear_case
            ), evaluation

        cited_rules    = await self._retrieve_rules(ticker, market, bull_case, bear_case)
        narrative_obj  = await self._synthesize(
            ticker=ticker,
            market=market,
            evaluation=evaluation,
            active_override_ids=active_override_ids,
            bull_case=bull_case,
            bear_case=bear_case,
            cited_rules=cited_rules,
        )

        return Judgment(
            signal=evaluation.final_signal_after_overrides,
            composite_score=evaluation.composite_score,
            overrides_active=active_override_ids,
            bull_case_summary=narrative_obj.bull_case_summary or _short_summary(bull_case),
            bear_case_summary=narrative_obj.bear_case_summary or _short_summary(bear_case),
            cited_rule_ids=[c["id"] for c in cited_rules],
            narrative=narrative_obj.narrative,
        ), evaluation

    async def _retrieve_rules(
        self,
        ticker: str,
        market: Market,
        bull_case: BullCase | None,
        bear_case: BearCase | None,
    ) -> list[dict[str, Any]]:
        if self.retriever is None:
            return []
        query_parts = [ticker, market]
        if bull_case is not None:
            query_parts.append(bull_case.thesis)
        if bear_case is not None:
            query_parts.append(bear_case.thesis)
        try:
            hits = await self.retriever.search(
                query=" ".join(query_parts),
                limit=self.rag_top_k,
                filters={"doc_type": "rule"},
            )
        except Exception as e:
            logger.warning("RAG retrieval failed (%s); judge proceeds without citations", e)
            return []
        return [
            {"id": h.metadata.get("rule_id", h.id), "score": h.score,
             "text": h.text[:400], "metadata": dict(h.metadata)}
            for h in hits
        ]

    async def _synthesize(
        self,
        *,
        ticker: str,
        market: Market,
        evaluation: EvaluationResult,
        active_override_ids: list[str],
        bull_case: BullCase | None,
        bear_case: BearCase | None,
        cited_rules: list[dict[str, Any]],
    ) -> JudgeNarrative:
        prompt = self._render_prompt(
            ticker=ticker, market=market, evaluation=evaluation,
            active_override_ids=active_override_ids,
            bull_case=bull_case, bear_case=bear_case, cited_rules=cited_rules,
        )
        info = {
            "ticker": ticker, "market": market, "evaluation": evaluation,
            "bull_case": bull_case, "bear_case": bear_case, "cited_rules": cited_rules,
        }
        narrator = self._narrator or self._resolve_default_narrator()
        try:
            return await narrator(prompt, info)
        except Exception as e:
            logger.warning("Judge narrator failed (%s); using templated synthesis", e)
            return _templated_synthesis(evaluation, bull_case, bear_case, cited_rules)

    def _render_prompt(
        self,
        *,
        ticker: str,
        market: Market,
        evaluation: EvaluationResult,
        active_override_ids: list[str],
        bull_case: BullCase | None,
        bear_case: BearCase | None,
        cited_rules: list[dict[str, Any]],
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return template.format(
            ticker=ticker,
            market=market,
            composite_score=evaluation.composite_score,
            signal=evaluation.final_signal_after_overrides,
            overrides_text=", ".join(active_override_ids) if active_override_ids else "(none)",
            bull_thesis=bull_case.thesis if bull_case else "(no bull case provided)",
            bear_thesis=bear_case.thesis if bear_case else "(no bear case provided)",
            cited_rules_text=(
                "\n".join(f"  [{c['id']}] {c['text'][:200]}" for c in cited_rules)
                if cited_rules else "  (RAG retrieval returned no relevant rules)"
            ),
            pillar_breakdown="\n".join(
                f"  - {p}: {s:.1f}" for p, s in evaluation.pillar_scores.items()
            ),
        )

    def _resolve_default_narrator(self) -> JudgeNarrator:
        from packages.agents.llm_provider import is_any_llm_configured

        if is_any_llm_configured():
            return self._openai_narrator()

        async def _offline(prompt: str, info: dict[str, Any]) -> JudgeNarrative:  # noqa: ARG001
            return _templated_synthesis(
                info["evaluation"], info["bull_case"], info["bear_case"], info["cited_rules"]
            )
        return _offline

    def _openai_narrator(self) -> JudgeNarrator:
        async def _call(prompt: str, info: dict[str, Any]) -> JudgeNarrative:  # noqa: ARG001
            from packages.agents._llm_helpers import openai_create_tracked
            from packages.agents.llm_provider import effective_chat_model, get_litellm_instructor_client

            client = get_litellm_instructor_client()
            model = effective_chat_model(self.openai_model)
            return await openai_create_tracked(
                client,
                model=model,
                response_model=JudgeNarrative,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        return _call


# ---------------------------------------------------------------------------
# Override-dominated synthesis (LLM bypassed — unchanged logic)
# ---------------------------------------------------------------------------

_SCORE_OVERRIDING_ACTIONS = frozenset({"FORCE_STRONG_SELL", "FORCE_SELL"})


def _is_score_overriding(action: str) -> bool:
    return action in _SCORE_OVERRIDING_ACTIONS


def _templated_override_judgment(
    evaluation: EvaluationResult,
    active_overrides: list[OverrideResult],
    bull_case: BullCase | None,
    bear_case: BearCase | None,
) -> Judgment:
    primary = active_overrides[0]
    others  = active_overrides[1:]

    if primary.action == "FORCE_STRONG_SELL":
        narrative = (
            f"Override [{primary.override_id}] {primary.name} has triggered. "
            f"This forces an immediate STRONG_SELL regardless of the composite score "
            f"of {evaluation.composite_score:.1f}/100. "
        )
    elif primary.action == "FORCE_SELL":
        narrative = (
            f"Override [{primary.override_id}] {primary.name} has triggered. "
            f"This forces a SELL regardless of composite score "
            f"({evaluation.composite_score:.1f}/100). "
        )
    else:
        narrative = (
            f"Override [{primary.override_id}] {primary.name} triggered "
            f"(composite {evaluation.composite_score:.1f}/100). "
        )

    if others:
        narrative += f"Additional overrides: {', '.join(o.override_id for o in others)}. "
    narrative += "Bull and bear cases do not change the outcome under a score-overriding event."

    return Judgment(
        signal=evaluation.final_signal_after_overrides,
        composite_score=evaluation.composite_score,
        overrides_active=[o.override_id for o in active_overrides],
        bull_case_summary=_short_summary(bull_case),
        bear_case_summary=_short_summary(bear_case),
        cited_rule_ids=[],
        narrative=narrative,
    )


def _templated_synthesis(
    evaluation: EvaluationResult,
    bull_case: BullCase | None,
    bear_case: BearCase | None,
    cited_rules: list[dict[str, Any]],
) -> JudgeNarrative:
    parts: list[str] = [
        f"Composite score is {evaluation.composite_score:.1f}/100 with "
        f"final signal {evaluation.final_signal_after_overrides}."
    ]
    if bull_case is not None:
        parts.append("Bull case: " + _truncate(bull_case.thesis, 160))
    if bear_case is not None:
        parts.append("Bear case: " + _truncate(bear_case.thesis, 160))
    if cited_rules:
        parts.append(f"RAG rules: {', '.join(c['id'] for c in cited_rules[:5])}.")
    parts.append(
        "Pillar breakdown: "
        + ", ".join(f"{p} {s:.0f}" for p, s in evaluation.pillar_scores.items())
        + "."
    )
    return JudgeNarrative(
        narrative=" ".join(parts),
        bull_case_summary=_short_summary(bull_case),
        bear_case_summary=_short_summary(bear_case),
    )


def _short_summary(case: BullCase | BearCase | None) -> str:
    if case is None:
        return ""
    text = case.thesis.split(".")[0].strip()
    return text + ("." if text and not text.endswith(".") else "")


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 3] + "..."


__all__ = ["Judge", "JudgeNarrator"]

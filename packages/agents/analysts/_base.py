"""Shared base class for the per-pillar analyst agents.

LLM backend: instructor structured outputs via LiteLLM (OpenAI, Anthropic,
Gemini, Mistral, Groq — whichever API key is configured first).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar, Sequence

from packages.core.rule_evaluator import (
    PillarEvaluation,
    RuleEvaluator,
    RuleResult,
)
from packages.shared.schemas import AnalystNarrative, AnalystReport, Market, Pillar

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "analyst_base.txt"

LLMNarrator = Callable[[str, "PromptInfo"], Awaitable[AnalystNarrative]]


class PromptInfo(dict[str, Any]):
    pass


# ---------------------------------------------------------------------------
# Default OpenAI narrator
# ---------------------------------------------------------------------------


class _OpenAINarrator:
    """Production narrator: instructor + LiteLLM, structured into ``AnalystNarrative``."""

    def __init__(
        self,
        model: str = "gpt-4o",
        max_tokens: int = 2048,
        temperature: float = 0.3,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def __call__(self, prompt: str, info: PromptInfo) -> AnalystNarrative:
        from packages.agents._llm_helpers import openai_create_tracked
        from packages.agents.llm_provider import effective_chat_model, get_litellm_instructor_client

        client = get_litellm_instructor_client()
        model = effective_chat_model(self.model)

        return await openai_create_tracked(
            client,
            model=model,
            response_model=AnalystNarrative,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )


# ---------------------------------------------------------------------------
# Base analyst
# ---------------------------------------------------------------------------


class BaseAnalyst:
    pillar: ClassVar[Pillar]
    categories: ClassVar[tuple[str, ...]]

    def __init__(
        self,
        evaluator: RuleEvaluator,
        narrator: LLMNarrator | None = None,
    ) -> None:
        if not getattr(self, "pillar", None):
            raise TypeError(f"{type(self).__name__} must declare class attribute 'pillar'")
        if not getattr(self, "categories", None):
            raise TypeError(f"{type(self).__name__} must declare class attribute 'categories'")
        self.evaluator = evaluator
        self._narrator = narrator

    async def analyze(
        self, context: dict[str, Any], ticker: str, market: Market
    ) -> AnalystReport:
        evaluation = self.evaluator.evaluate_pillar(
            ticker, market, context, self.categories
        )
        score    = self.aggregate(evaluation.per_category_scores, evaluation)
        prompt   = self._render_prompt(ticker, market, score, evaluation, context)
        info     = PromptInfo(
            pillar=self.pillar,
            categories=list(self.categories),
            ticker=ticker,
            market=market,
            score=score,
            evaluation=evaluation,
            rule_results=evaluation.rule_results,
            per_category_scores=dict(evaluation.per_category_scores),
            rules_evaluated=evaluation.rules_evaluated,
            rules_skipped=evaluation.rules_skipped,
        )
        narrative = await self._call_narrator(prompt, info)
        narrative = self._sanitize_citations(narrative, evaluation.rule_results)
        return AnalystReport(
            pillar=self.pillar,
            score=score,
            narrative=narrative.narrative,
            top_signals=list(narrative.top_signals),
            citations=list(narrative.citations),
            confidence=narrative.confidence,
        )

    def aggregate(
        self,
        per_category_scores: dict[str, float],
        evaluation: PillarEvaluation,
    ) -> float:
        active = [
            score
            for cat, score in per_category_scores.items()
            if any(r.category == cat for r in evaluation.rule_results)
        ]
        if not active:
            return 50.0
        return sum(active) / len(active)

    async def _call_narrator(self, prompt: str, info: PromptInfo) -> AnalystNarrative:
        narrator = self._narrator
        if narrator is None:
            narrator = self._resolve_default_narrator()
        try:
            return await narrator(prompt, info)
        except Exception as e:
            logger.warning(
                "%s narrator failed (%s); falling back to templated narrative",
                type(self).__name__, e,
            )
            return _templated_narrative(self.pillar, info)

    def _resolve_default_narrator(self) -> LLMNarrator:
        from packages.agents.llm_provider import is_any_llm_configured

        if is_any_llm_configured():
            return _OpenAINarrator()

        async def _offline(prompt: str, info: PromptInfo) -> AnalystNarrative:
            return _templated_narrative(self.pillar, info)
        return _offline

    def _render_prompt(
        self,
        ticker: str,
        market: Market,
        score: float,
        evaluation: PillarEvaluation,
        context: dict[str, Any],
    ) -> str:
        template = _PROMPT_PATH.read_text(encoding="utf-8")
        return template.format(
            pillar_name=self.pillar,
            ticker=ticker,
            market=market,
            pillar_score=score,
            rules_evaluated=evaluation.rules_evaluated,
            rules_skipped=evaluation.rules_skipped,
            category_breakdown=_format_category_breakdown(evaluation),
            rule_results_text=_format_rule_results(evaluation.rule_results),
            raw_context_excerpt=_format_context_excerpt(context, evaluation.rule_results),
        )

    @staticmethod
    def _sanitize_citations(
        narrative: AnalystNarrative,
        rule_results: list[RuleResult],
    ) -> AnalystNarrative:
        valid_ids      = {r.rule_id for r in rule_results}
        clean_citations = [c for c in narrative.citations if c in valid_ids]
        clean_signals: list[str] = []
        for sig in narrative.top_signals:
            head = sig.split(":", 1)[0].strip() if ":" in sig else ""
            if head and head not in valid_ids:
                continue
            clean_signals.append(sig)
        if (
            len(clean_citations) == len(narrative.citations)
            and len(clean_signals) == len(narrative.top_signals)
        ):
            return narrative
        return AnalystNarrative(
            narrative=narrative.narrative,
            top_signals=clean_signals,
            citations=clean_citations,
            confidence=narrative.confidence,
        )


# ---------------------------------------------------------------------------
# Prompt formatting helpers (unchanged)
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _format_category_breakdown(evaluation: PillarEvaluation) -> str:
    lines: list[str] = []
    for cat in evaluation.categories:
        score = evaluation.per_category_scores.get(cat, 50.0)
        in_cat = [r for r in evaluation.rule_results if r.category == cat]
        ev = sum(1 for r in in_cat if r.tier != "skipped")
        sk = sum(1 for r in in_cat if r.tier == "skipped")
        lines.append(f"  - {cat}: {score:.1f} ({ev} evaluated, {sk} skipped)")
    return "\n".join(lines) if lines else "  (no categories)"


def _format_rule_results(results: Sequence[RuleResult]) -> str:
    if not results:
        return "  (no rules in this pillar)"
    lines: list[str] = []
    for r in results:
        if r.tier == "skipped":
            lines.append(f"  [{r.rule_id}] {r.rule_name} - tier: skipped ({r.skipped_reason})")
        else:
            lines.append(
                f"  [{r.rule_id}] {r.rule_name} - tier: {r.tier}, score: {r.score:.1f}"
            )
            if r.matched_condition:
                lines.append(f"      matched: {r.matched_condition}")
    return "\n".join(lines)


def _format_context_excerpt(
    context: dict[str, Any], rule_results: Sequence[RuleResult]
) -> str:
    import re
    interesting_keys: set[str] = {"sector", "market_regime", "market"}
    token_re = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    for r in rule_results:
        if r.matched_condition:
            for tok in token_re.findall(r.matched_condition):
                if tok in context:
                    interesting_keys.add(tok)
    if not interesting_keys:
        items = list(context.items())[:15]
    else:
        items = [(k, context[k]) for k in sorted(interesting_keys) if k in context]
    if not items:
        return "  (no relevant context fields)"
    return "\n".join(f"  {k}: {_compact_repr(v)}" for k, v in items)


def _compact_repr(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    s = repr(value)
    return s if len(s) <= 80 else s[:77] + "..."


# ---------------------------------------------------------------------------
# Templated fallback narrator (unchanged)
# ---------------------------------------------------------------------------

def _templated_narrative(pillar: Pillar, info: PromptInfo) -> AnalystNarrative:
    rule_results: list[RuleResult]  = list(info.get("rule_results", []))
    per_cat: dict[str, float]       = dict(info.get("per_category_scores", {}))
    rules_evaluated: int            = int(info.get("rules_evaluated", 0))
    rules_skipped: int              = int(info.get("rules_skipped", 0))

    if rules_evaluated == 0:
        return AnalystNarrative(
            narrative=(
                f"The {pillar} pillar has no evaluable rules for this ticker; "
                f"all {rules_skipped} rules were skipped due to missing data."
            ),
            top_signals=[],
            citations=[],
            confidence=0.2,
        )

    buys  = sorted(
        (r for r in rule_results if r.tier in ("strong_buy", "buy")), key=lambda r: -r.score
    )[:3]
    sells = sorted(
        (r for r in rule_results if r.tier in ("strong_sell", "sell")), key=lambda r: r.score
    )[:3]

    cat_summary = ", ".join(f"{c}={s:.0f}" for c, s in per_cat.items())

    if buys and not sells:
        narr = (
            f"The {pillar} pillar is broadly positive (per-category: {cat_summary}). "
            f"Strongest signals: {', '.join(r.rule_id for r in buys)}. "
            f"No sell-tier rules fired; {rules_skipped} rules skipped."
        )
    elif sells and not buys:
        narr = (
            f"The {pillar} pillar leans negative (per-category: {cat_summary}). "
            f"Triggering rules: {', '.join(r.rule_id for r in sells)}. "
            f"No supportive signals; {rules_skipped} rules skipped."
        )
    elif buys and sells:
        narr = (
            f"The {pillar} pillar is mixed (per-category: {cat_summary}). "
            f"Bull: {', '.join(r.rule_id for r in buys)}; "
            f"Bear: {', '.join(r.rule_id for r in sells)}. "
            f"{rules_skipped} rules skipped."
        )
    else:
        narr = (
            f"The {pillar} pillar is neutral (per-category: {cat_summary}); "
            f"{rules_evaluated} rules ran but none fired buy- or sell-tier conditions."
        )

    top_signals = [
        f"{r.rule_id}: {r.rule_name} [{r.tier}, score {r.score:.0f}]"
        for r in buys + sells
    ]
    citations = [r.rule_id for r in buys + sells]
    total      = rules_evaluated + rules_skipped
    confidence = round(0.3 + 0.4 * (rules_evaluated / total if total else 0.0), 2)

    return AnalystNarrative(
        narrative=narr,
        top_signals=top_signals,
        citations=citations,
        confidence=confidence,
    )

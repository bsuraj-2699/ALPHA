"""Bull / Bear debate agents — instructor + LiteLLM (multi-provider)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, ClassVar

from packages.shared.schemas import AnalystReport, BearCase, BullCase, Market

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

DebateOutput  = BullCase | BearCase
DebateNarrator = Callable[[str, dict[str, Any]], Awaitable[DebateOutput]]


class _DebateAgent:
    side:           ClassVar[str]
    response_model: ClassVar[type[BullCase] | type[BearCase]]
    prompt_path:    ClassVar[Path]

    def __init__(
        self,
        narrator: DebateNarrator | None = None,
        openai_model: str = "gpt-4o",
        max_tokens: int = 1500,
        temperature: float = 0.3,
    ) -> None:
        self._narrator    = narrator
        self.openai_model = openai_model
        self.max_tokens   = max_tokens
        self.temperature  = temperature

    async def make_case(
        self,
        analyst_reports: list[AnalystReport],
        ticker: str,
        market: Market,
    ) -> BullCase | BearCase:
        prompt  = self._render_prompt(analyst_reports, ticker, market)
        info    = {
            "side": self.side, "ticker": ticker, "market": market,
            "analyst_reports": analyst_reports,
        }
        narrator = self._narrator or self._resolve_default_narrator()
        try:
            return await narrator(prompt, info)
        except Exception as e:
            logger.warning("%s narrator failed (%s); using templated fallback", self.side, e)
            return _templated_case(self.side, self.response_model, analyst_reports)

    def _render_prompt(
        self, analyst_reports: list[AnalystReport], ticker: str, market: Market
    ) -> str:
        template = self.prompt_path.read_text(encoding="utf-8")
        return template.format(
            ticker=ticker,
            market=market,
            analyst_reports=_format_reports(analyst_reports),
        )

    def _resolve_default_narrator(self) -> DebateNarrator:
        from packages.agents.llm_provider import is_any_llm_configured

        if is_any_llm_configured():
            return self._openai_narrator()

        async def _offline(prompt: str, info: dict[str, Any]) -> DebateOutput:  # noqa: ARG001
            return _templated_case(self.side, self.response_model, info["analyst_reports"])
        return _offline

    def _openai_narrator(self) -> DebateNarrator:
        async def _call(prompt: str, info: dict[str, Any]) -> DebateOutput:  # noqa: ARG001
            from packages.agents._llm_helpers import openai_create_tracked
            from packages.agents.llm_provider import effective_chat_model, get_litellm_instructor_client

            client = get_litellm_instructor_client()
            model = effective_chat_model(self.openai_model)
            return await openai_create_tracked(
                client,
                model=model,
                response_model=self.response_model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )
        return _call


class BullAgent(_DebateAgent):
    side:           ClassVar[str]                 = "bull"
    response_model: ClassVar[type[BullCase]]      = BullCase
    prompt_path:    ClassVar[Path]                = _PROMPTS_DIR / "debate_bull.txt"


class BearAgent(_DebateAgent):
    side:           ClassVar[str]                 = "bear"
    response_model: ClassVar[type[BearCase]]      = BearCase
    prompt_path:    ClassVar[Path]                = _PROMPTS_DIR / "debate_bear.txt"


# ---------------------------------------------------------------------------
# Helpers (unchanged logic)
# ---------------------------------------------------------------------------

def _format_reports(reports: list[AnalystReport]) -> str:
    if not reports:
        return "  (no analyst reports)"
    blocks: list[str] = []
    for r in reports:
        cites   = ", ".join(r.citations)  if r.citations   else "(none)"
        signals = "\n      - ".join(r.top_signals) if r.top_signals else "(none)"
        blocks.append(
            f"[{r.pillar.upper()}] score {r.score:.1f}/100, confidence {r.confidence:.2f}\n"
            f"    citations: {cites}\n"
            f"    top_signals:\n      - {signals}\n"
            f"    narrative: {r.narrative}"
        )
    return "\n\n".join(blocks)


def _templated_case(
    side: str,
    response_model: type[BullCase] | type[BearCase],
    reports: list[AnalystReport],
) -> BullCase | BearCase:
    if not reports:
        return response_model(
            thesis=f"No analyst reports available; the {side} case cannot be made.",
            key_supports=[],
            confidence=0.1,
        )
    if side == "bull":
        sorted_reports = sorted(reports, key=lambda r: -r.score)
        leading        = sorted_reports[:3]
        threshold      = 50.0
        sentiment_word = "above-neutral"
        flavor         = "strengths"
    else:
        sorted_reports = sorted(reports, key=lambda r: r.score)
        leading        = sorted_reports[:3]
        threshold      = 50.0
        sentiment_word = "below-neutral"
        flavor         = "weaknesses"

    qualifying = [r for r in leading if (r.score >= threshold) == (side == "bull")]
    qualifying  = qualifying or leading

    pillar_scores = ", ".join(f"{r.pillar} {r.score:.0f}/100" for r in qualifying)
    citations: list[str] = []
    for r in qualifying:
        citations.extend(r.citations[:2])
    citations = list(dict.fromkeys(citations))[:5]

    if side == "bull":
        thesis = (
            f"The bullish case rests on {flavor} in: {pillar_scores}. "
            f"These are {sentiment_word} pillars driven by rules including "
            f"{', '.join(citations) if citations else '(no specific rule citations)'}. "
            f"The remaining pillars are not actively negative, which provides cover for "
            f"a long entry."
        )
    else:
        thesis = (
            f"The bearish case rests on {flavor} in: {pillar_scores}. "
            f"These are {sentiment_word} pillars driven by rules including "
            f"{', '.join(citations) if citations else '(no specific rule citations)'}. "
            f"Positive pillars do not offset the deterioration in the weak ones."
        )

    key_supports = [
        f"{r.pillar} pillar {r.score:.0f}/100"
        + (f" (driven by {', '.join(r.citations[:2])})" if r.citations else "")
        for r in qualifying
    ]

    if side == "bull":
        deltas = [max(0.0, r.score - 50.0) / 50.0 for r in reports]
    else:
        deltas = [max(0.0, 50.0 - r.score) / 50.0 for r in reports]
    confidence = round(min(1.0, sum(deltas) / max(1, len(reports))), 2)

    return response_model(thesis=thesis, key_supports=key_supports, confidence=confidence)


__all__ = ["BullAgent", "BearAgent", "DebateNarrator"]

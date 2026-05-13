"""LangGraph orchestrator for the multi-analyst financial-decision pipeline.

LLM backend: instructor structured outputs via LiteLLM (OpenAI, Anthropic,
Gemini, Mistral, Groq — whichever API key is configured).
Extended thinking removed (Anthropic-only feature).

Graph topology
--------------
    parse  →  context_build  →  | fundamentals |
                                | technicals   |  (parallel analysts)
                                | sentiment    |
                                | macro        |
                                | risk         |
                                →  debate  (bull + bear parallel)
                                →  judge
                                →  decide
                                →  END
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from packages.agents.analysts import (
    BaseAnalyst,
    FundamentalAnalyst,
    MacroAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)
from packages.agents.debate import BearAgent, BullAgent
from packages.agents.decision import DecisionAgent
from packages.agents.judge import Judge
from packages.agents.state import AgentState
from packages.core.rule_evaluator import RuleEvaluator
from packages.data.context_builder import ContextBuilder
from packages.shared.config import (
    ANALYST_PILLAR_TO_MODE_PILLAR,
    DEFAULT_MODE,
    MODE_PILLAR_TO_ANALYST_PILLAR,
    ModeConfig,
    get_mode_config,
)
from packages.shared.observability import (
    EventPublisher,
    publish_event,
    reset_run_context,
    set_run_context,
)
from packages.shared.schemas import (
    AnalystReport,
    BearCase,
    BullCase,
    Decision,
    Judgment,
    Market,
    Mode,
    ParsedQuery,
    Pillar,
    ReasoningStep,
)

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).resolve().parents[1] / "core" / "rules.json"

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS   = 4096

PARSE_SYSTEM_PROMPT = """You parse a single user query about an Indian stock (NSE/BSE) into a strict JSON record.

This system covers ONLY the Indian equity market. All tickers are NSE-listed.

Rules:
- ticker: return the BARE NSE symbol only — no suffix, no exchange prefix.
    Examples: RELIANCE, TCS, INFY, HDFCBANK, SBIN
    Do NOT return RELIANCE.NS or NSE_EQ|... — just the bare symbol.
- market: always "IN". This system only handles Indian equities.
- intent: "analyze" by default. Use "compare" only if the user explicitly compares two tickers.
  Use "monitor" only if the user asks for ongoing alerts.
- horizon_days: integer if the user mentions a horizon ("3 months" -> 90, "1 year" -> 365); else null.
- notes: optional one-sentence clarification of anything unusual; otherwise null.

Always emit a valid JSON record."""

_PILLAR_TO_STATE_KEY: dict[Pillar, str] = {
    "fundamentals": "fundamental_report",
    "technicals":   "technical_report",
    "sentiment":    "sentiment_report",
    "macro":        "macro_report",
    "risk":         "risk_report",
}


# ---------------------------------------------------------------------------
# Heuristic fallback parser (unchanged)
# ---------------------------------------------------------------------------

_TICKER_DOTNS_RE  = re.compile(r"\b([A-Z][A-Z0-9]*\.NS)\b")
_TICKER_DOTBO_RE  = re.compile(r"\b([A-Z][A-Z0-9]*\.BO)\b")
_BARE_TICKER_RE   = re.compile(r"\b([A-Z]{1,8})\b")
_HORIZON_RE = re.compile(
    r"(\d+)\s*(day|days|week|weeks|month|months|year|years|yr|yrs)\b",
    re.IGNORECASE,
)
_TICKER_NOISE = {
    "I","A","AND","OR","BUY","SELL","HOLD","THE","OF","ON","FOR",
    "STOCK","STOCKS","ANALYZE","ANALYSIS","WHAT","IS","DO","SHOULD",
    "NSE","BSE","INR","USD","HORIZON","PE","EV",
}


def _heuristic_parse(query: str) -> ParsedQuery:
    from packages.shared.ticker_registry import normalize as _norm

    m = _TICKER_DOTNS_RE.search(query) or _TICKER_DOTBO_RE.search(query)
    if m:
        return ParsedQuery(
            ticker=_norm(m.group(1)),  # RELIANCE.NS → RELIANCE
            market="IN",
            intent="analyze",
            horizon_days=_extract_horizon(query),
            notes="Heuristic parse (no LLM API key or LLM call failed).",
        )
    candidates = [c for c in _BARE_TICKER_RE.findall(query) if c not in _TICKER_NOISE]
    ticker = _norm(candidates[0]) if candidates else "RELIANCE"  # default to RELIANCE for IN market
    return ParsedQuery(
        ticker=ticker,
        market="IN",  # this system is IN-only
        intent="analyze",
        horizon_days=_extract_horizon(query),
        notes="Heuristic parse (no LLM API key or LLM call failed).",
    )


def _extract_horizon(query: str) -> int | None:
    m = _HORIZON_RE.search(query)
    if not m:
        return None
    n    = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("day"):   return n
    if unit.startswith("week"):  return n * 7
    if unit.startswith("month"): return n * 30
    if unit.startswith("year") or unit.startswith("yr"): return n * 365
    return None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """Owns the compiled LangGraph and exposes :meth:`arun` / :meth:`aresume`."""

    def __init__(
        self,
        context_builder: ContextBuilder | None = None,
        evaluator: RuleEvaluator | None = None,
        analysts: dict[Pillar, BaseAnalyst] | None = None,
        bull_agent: BullAgent | None = None,
        bear_agent: BearAgent | None = None,
        judge: Judge | None = None,
        decision_agent: DecisionAgent | None = None,
        retriever: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        auto_approve_strong_signals: bool = True,
        openai_model: str = DEFAULT_OPENAI_MODEL,
        max_tokens:   int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._context_builder = context_builder
        self._evaluator       = evaluator or RuleEvaluator(_RULES_PATH)

        self._analysts: dict[Pillar, BaseAnalyst] = (
            analysts if analysts is not None else self._build_default_analysts()
        )
        missing = set(_PILLAR_TO_STATE_KEY) - set(self._analysts)
        if missing:
            raise ValueError(f"Orchestrator missing analysts for pillars: {sorted(missing)}")

        self._bull          = bull_agent   or BullAgent()
        self._bear          = bear_agent   or BearAgent()
        self._judge         = judge        or Judge(self._evaluator, retriever=retriever)
        self._decision_agent = decision_agent or DecisionAgent()

        self.auto_approve_strong_signals = auto_approve_strong_signals
        self.openai_model = openai_model
        self.max_tokens   = max_tokens

        self._checkpointer = checkpointer or MemorySaver()
        self._graph        = self._build_graph()

    def _build_default_analysts(self) -> dict[Pillar, BaseAnalyst]:
        return {
            "fundamentals": FundamentalAnalyst(self._evaluator),
            "technicals":   TechnicalAnalyst(self._evaluator),
            "sentiment":    SentimentAnalyst(self._evaluator),
            "macro":        MacroAnalyst(self._evaluator),
            "risk":         RiskAnalyst(self._evaluator),
        }

    # ----- public API -------------------------------------------------------

    @staticmethod
    def initial_state(
        query: str,
        *,
        auto_approve_strong: bool = True,
        mode: Mode = DEFAULT_MODE,
    ) -> AgentState:
        return {
            "query": query,
            "ticker": "",
            "market": "IN",  # this system is IN-only
            "mode": mode,
            "context": {},
            "fundamental_report": None,
            "technical_report":   None,
            "sentiment_report":   None,
            "macro_report":       None,
            "risk_report":        None,
            "bull_case":          None,
            "bear_case":          None,
            "retrieved_rules":    [],
            "evaluation":         None,
            "judgment":           None,
            "decision":           None,
            "reasoning_trace":    [],
            "error":              None,
            "auto_approve_strong": auto_approve_strong,
        }

    async def arun(
        self,
        query: str,
        *,
        thread_id: str | None = None,
        ticker: str | None = None,
        market: Market | None = None,
        context_overrides: dict[str, Any] | None = None,
        event_publisher: EventPublisher | None = None,
        mode: Mode | None = None,
    ) -> AgentState:
        thread_id = thread_id or uuid.uuid4().hex
        config    = {"configurable": {"thread_id": thread_id}}
        state     = self.initial_state(
            query,
            auto_approve_strong=self.auto_approve_strong_signals,
            mode=mode or DEFAULT_MODE,
        )
        if ticker:
            state["ticker"] = ticker
            state["market"] = market or "IN"
        if context_overrides:
            state["context"] = _sanitize_for_checkpoint(dict(context_overrides))

        tokens = set_run_context(thread_id, event_publisher)
        try:
            result = await self._graph.ainvoke(state, config=config)
        finally:
            reset_run_context(tokens)

        result_dict: dict[str, Any] = dict(result) if result is not None else {}
        result_dict["_thread_id"] = thread_id
        return result_dict  # type: ignore[return-value]

    async def aresume(
        self,
        thread_id: str,
        response: str,
        *,
        event_publisher: EventPublisher | None = None,
    ) -> AgentState:
        from langgraph.types import Command

        config = {"configurable": {"thread_id": thread_id}}
        tokens = set_run_context(thread_id, event_publisher)
        try:
            result = await self._graph.ainvoke(Command(resume=response), config=config)
        finally:
            reset_run_context(tokens)

        result_dict: dict[str, Any] = dict(result) if result is not None else {}
        result_dict["_thread_id"] = thread_id
        return result_dict  # type: ignore[return-value]

    # ----- graph construction -----------------------------------------------

    def _build_graph(self) -> Any:
        g: StateGraph = StateGraph(AgentState)
        g.add_node("parse",         self._parse_node)
        g.add_node("context_build", self._context_build_node)
        for pillar in _PILLAR_TO_STATE_KEY:
            g.add_node(pillar, self._make_analyst_node(self._analysts[pillar]))
        g.add_node("debate", self._debate_node)
        g.add_node("judge",  self._judge_node)
        g.add_node("decide", self._decide_node)

        g.add_edge(START, "parse")
        g.add_edge("parse", "context_build")
        g.add_conditional_edges(
            "context_build",
            self._route_active_analysts,
            list(_PILLAR_TO_STATE_KEY),
        )
        for pillar in _PILLAR_TO_STATE_KEY:
            g.add_edge(pillar, "debate")
        g.add_edge("debate", "judge")
        g.add_edge("judge",  "decide")
        g.add_edge("decide", END)

        return g.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _route_active_analysts(state: AgentState) -> list[str]:
        mode = state.get("mode") or DEFAULT_MODE
        try:
            cfg = get_mode_config(mode)
        except ValueError:
            return list(_PILLAR_TO_STATE_KEY)
        active: list[str] = []
        for pillar in _PILLAR_TO_STATE_KEY:
            mode_pillar = ANALYST_PILLAR_TO_MODE_PILLAR.get(pillar)
            if mode_pillar is None:
                continue
            if mode_pillar in cfg.active_pillars:
                active.append(pillar)
        return active or list(_PILLAR_TO_STATE_KEY)

    # ----- nodes ------------------------------------------------------------

    async def _parse_node(self, state: AgentState) -> dict[str, Any]:
        async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
            preset_ticker = state.get("ticker")
            if preset_ticker:
                summary = f"Pre-parsed: ticker={preset_ticker} market={state.get('market','IN')}"
                return ({}, summary, {"pre_parsed": True})

            query  = state.get("query", "") or ""
            parsed = await self._parse_query(query)
            summary = (
                f"Parsed → ticker={parsed.ticker} market={parsed.market} "
                f"intent={parsed.intent}"
                + (f" horizon={parsed.horizon_days}d" if parsed.horizon_days else "")
            )
            return (
                {"ticker": parsed.ticker, "market": parsed.market},
                summary,
                parsed.model_dump(),
            )
        return await _timed("parse", runner)

    async def _parse_query(self, query: str) -> ParsedQuery:
        from packages.agents.llm_provider import is_any_llm_configured

        if not is_any_llm_configured():
            return _heuristic_parse(query)
        try:
            result = await self._parse_with_openai(query)
            # Always normalize: strip .NS/.BO suffix so internal ticker is bare (INFY not INFY.NS)
            from packages.shared.ticker_registry import normalize
            result = result.model_copy(update={
                "ticker": normalize(result.ticker),
                "market": "IN",  # this system is IN-only; override any US guess
            })
            return result
        except Exception as e:
            logger.warning("LLM parse failed (%s); falling back to heuristic", e)
            return _heuristic_parse(query)

    async def _parse_with_openai(self, query: str) -> ParsedQuery:
        from packages.agents._llm_helpers import openai_create_tracked
        from packages.agents.llm_provider import effective_chat_model, get_litellm_instructor_client

        client = get_litellm_instructor_client()
        model = effective_chat_model(self.openai_model)
        return await openai_create_tracked(
            client,
            model=model,
            response_model=ParsedQuery,
            max_tokens=self.max_tokens,
            temperature=0.3,
            messages=[
                {"role": "system", "content": PARSE_SYSTEM_PROMPT},
                {"role": "user",   "content": query},
            ],
        )

    async def _context_build_node(self, state: AgentState) -> dict[str, Any]:
        async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
            ticker       = state["ticker"]
            market       = state["market"]
            mode: Mode   = state.get("mode") or DEFAULT_MODE
            try:
                mode_config: ModeConfig | None = get_mode_config(mode)
            except ValueError:
                mode_config = None
            seed_overrides = dict(state.get("context") or {})
            builder = self._context_builder or _build_default_builder(market, mode_config)
            try:
                ctx = await builder.build(ticker, market)
            except Exception as e:
                logger.warning("ContextBuilder failed for %s/%s: %s", ticker, market, e)
                return (
                    {"context": seed_overrides, "error": f"context_build: {e}"},
                    f"context build failed: {e}",
                    {"keys": len(seed_overrides), "error": str(e)},
                )
            ctx            = _sanitize_for_checkpoint(ctx)
            seed_overrides = _sanitize_for_checkpoint(seed_overrides)
            merged: dict[str, Any] = {**ctx, **seed_overrides}
            summary = (
                f"Built context with {len(merged)} keys for {ticker} ({market})"
                + (f" (+{len(seed_overrides)} caller overrides)" if seed_overrides else "")
            )
            return (
                {"context": merged},
                summary,
                {"keys": len(merged), "overrides": len(seed_overrides),
                 "sample": sorted(merged.keys())[:10]},
            )
        return await _timed("context_build", runner)

    def _make_analyst_node(
        self, analyst: BaseAnalyst
    ) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
        state_key = _PILLAR_TO_STATE_KEY[analyst.pillar]
        pillar    = analyst.pillar

        async def _node(state: AgentState) -> dict[str, Any]:
            async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
                ctx    = state.get("context") or {}
                ticker = state.get("ticker", "") or ""
                market = state.get("market", "IN")
                if not ctx:
                    return (
                        {},
                        f"{pillar} analyst skipped: empty context",
                        {"pillar": pillar, "skipped": True, "reason": "empty_context"},
                    )
                report  = await analyst.analyze(ctx, ticker, market)
                summary = (
                    f"{pillar} analyst → score {report.score:.1f} "
                    f"({len(report.citations)} citations, conf {report.confidence:.2f})"
                )
                payload = {
                    "pillar": report.pillar, "score": report.score,
                    "n_signals": len(report.top_signals),
                    "n_citations": len(report.citations),
                    "confidence": report.confidence,
                }
                return {state_key: report}, summary, payload
            return await _timed(pillar, runner)
        return _node

    async def _debate_node(self, state: AgentState) -> dict[str, Any]:
        async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
            ticker = state.get("ticker", "") or ""
            market = state.get("market", "IN")
            reports: list[AnalystReport] = [
                r for r in (
                    state.get("fundamental_report"),
                    state.get("technical_report"),
                    state.get("sentiment_report"),
                    state.get("macro_report"),
                    state.get("risk_report"),
                ) if r is not None
            ]
            if not reports:
                return (
                    {},
                    "debate skipped: no analyst reports",
                    {"skipped": True, "reason": "no_reports"},
                )
            bull, bear = await asyncio.gather(
                self._bull.make_case(reports, ticker, market),
                self._bear.make_case(reports, ticker, market),
            )
            assert isinstance(bull, BullCase)
            assert isinstance(bear, BearCase)
            summary = (
                f"debate → bull conf {bull.confidence:.2f}, "
                f"bear conf {bear.confidence:.2f}"
            )
            payload = {
                "bull_confidence": bull.confidence, "bear_confidence": bear.confidence,
                "bull_supports": len(bull.key_supports),
                "bear_supports": len(bear.key_supports),
            }
            return {"bull_case": bull, "bear_case": bear}, summary, payload
        return await _timed("debate", runner)

    async def _judge_node(self, state: AgentState) -> dict[str, Any]:
        async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
            ctx    = state.get("context") or {}
            ticker = state.get("ticker", "")
            market = state.get("market", "IN")
            mode: Mode = state.get("mode") or DEFAULT_MODE
            if not ctx:
                return (
                    {},
                    "judge skipped: empty context",
                    {"skipped": True, "reason": "empty_context"},
                )
            try:
                category_weights: dict[str, float] | None = (
                    get_mode_config(mode).category_weights()
                )
            except ValueError:
                category_weights = None
            judgment, evaluation = await self._judge.judge(
                ticker=ticker, market=market, context=ctx,
                bull_case=state.get("bull_case"),
                bear_case=state.get("bear_case"),
                category_weights=category_weights,
                mode=mode,
            )
            summary = (
                f"judge → {judgment.signal} "
                f"({judgment.composite_score:.1f}/100"
                + (
                    f", overrides: {','.join(judgment.overrides_active)}"
                    if judgment.overrides_active else ""
                )
                + ")"
            )
            payload = {
                "signal": judgment.signal,
                "composite_score": judgment.composite_score,
                "overrides_active": judgment.overrides_active,
                "n_cited_rules": len(judgment.cited_rule_ids),
                "rules_evaluated": evaluation.rules_evaluated_count,
            }
            return (
                {"evaluation": evaluation, "judgment": judgment},
                summary, payload,
            )
        return await _timed("judge", runner)

    async def _decide_node(self, state: AgentState) -> dict[str, Any]:
        async def runner() -> tuple[dict[str, Any], str, dict[str, Any]]:
            judgment: Judgment | None = state.get("judgment")
            evaluation  = state.get("evaluation")
            ctx         = state.get("context") or {}
            ticker      = state.get("ticker", "") or ""
            market: Market = state.get("market", "IN")
            mode: Mode  = state.get("mode") or DEFAULT_MODE

            if judgment is None:
                fallback_coverage = (
                    evaluation.data_coverage_pct if evaluation is not None else 0.0
                )
                decision = Decision(
                    ticker=ticker or "UNKNOWN", market=market,
                    signal="HOLD", confidence=50.0, position_size_pct=0.0,
                    entry_price=None, stop_loss=None, target_price=None,
                    rationale="Defensive HOLD - judge produced no Judgment.",
                    citations=[], overrides_active=[], requires_human_review=False,
                    data_coverage_pct=fallback_coverage,
                    warning=(
                        "Low data coverage — treat signal with caution"
                        if fallback_coverage < 60.0 else None
                    ),
                    mode=mode,
                    timestamp=datetime.now(timezone.utc),
                )
                return (
                    {"decision": decision},
                    "decide → defensive HOLD (no judgment)",
                    {"signal": "HOLD", "defensive": True},
                )

            coverage = evaluation.data_coverage_pct if evaluation is not None else 100.0
            decision = self._decision_agent.build(
                ticker=ticker, market=market, judgment=judgment,
                context=ctx, data_coverage_pct=coverage, mode=mode,
            )

            if (
                decision.signal in ("STRONG_BUY", "STRONG_SELL")
                and not state.get("auto_approve_strong", True)
            ):
                from langgraph.types import interrupt

                response = interrupt(
                    {
                        "type": "human_review_required",
                        "ticker": ticker, "market": market,
                        "signal": decision.signal,
                        "confidence": decision.confidence,
                        "position_size_pct": decision.position_size_pct,
                        "rationale": decision.rationale,
                        "overrides_active": decision.overrides_active,
                        "prompt": (
                            f"{decision.signal} for {ticker} ({market}) at "
                            f"confidence {decision.confidence:.1f}/100. "
                            f"Reply 'approve' to finalize or any other text to downgrade to HOLD."
                        ),
                    }
                )
                if response != "approve":
                    decision = decision.model_copy(
                        update={
                            "signal": "HOLD",
                            "position_size_pct": 0.0,
                            "entry_price": None,
                            "stop_loss": None,
                            "target_price": None,
                            "rationale": (
                                f"Human reviewer rejected the {decision.signal} "
                                f"recommendation; downgraded to HOLD. Original "
                                f"rationale: {decision.rationale}"
                            ),
                            "requires_human_review": False,
                        }
                    )
                    summary = "decide → HOLD (rejected by reviewer)"
                else:
                    summary = (
                        f"decide → {decision.signal} (approved by reviewer, "
                        f"size {decision.position_size_pct:.1f}%)"
                    )
            else:
                summary = (
                    f"decide → {decision.signal} "
                    f"(size {decision.position_size_pct:.1f}%, "
                    f"conf {decision.confidence:.1f}/100)"
                )

            payload = {
                "signal": decision.signal,
                "confidence": decision.confidence,
                "position_size_pct": decision.position_size_pct,
                "overrides_active": decision.overrides_active,
                "requires_human_review": decision.requires_human_review,
            }
            return {"decision": decision}, summary, payload
        return await _timed("decide", runner)


# ---------------------------------------------------------------------------
# Helpers (unchanged)
# ---------------------------------------------------------------------------

async def _timed(
    node: str,
    runner: Callable[[], Awaitable[tuple[dict[str, Any], str, dict[str, Any]]]],
) -> dict[str, Any]:
    from langgraph.errors import GraphInterrupt

    await publish_event("agent_start", {"node": node})
    t0 = time.perf_counter()
    try:
        update, summary, payload = await runner()
    except GraphInterrupt:
        raise
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.exception("node %s raised", node)
        step = ReasoningStep(
            node=node,
            timestamp=datetime.now(timezone.utc),
            summary=f"error: {e}",
            payload={"error": str(e)},
            duration_ms=elapsed,
        )
        await publish_event("error", {"node": node, "error": str(e), "duration_ms": elapsed})
        return {"reasoning_trace": [step], "error": f"{node}: {e}"}

    elapsed = (time.perf_counter() - t0) * 1000
    step = ReasoningStep(
        node=node,
        timestamp=datetime.now(timezone.utc),
        summary=summary,
        payload=payload,
        duration_ms=elapsed,
    )
    await publish_event(
        "agent_complete",
        {"node": node, "summary": summary, "duration_ms": elapsed, "payload": payload},
    )
    await publish_event("thinking", step.model_dump(mode="json"))

    if "decision" in update and update["decision"] is not None:
        decision = update["decision"]
        try:
            await publish_event("decision", decision.model_dump(mode="json"))
        except AttributeError:
            await publish_event("decision", dict(decision))

    out = dict(update)
    out["reasoning_trace"] = [step]
    return out


def _force_utf8_stdout() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _build_default_builder(
    market: Market, mode_config: ModeConfig | None = None
) -> ContextBuilder:
    from packages.data.context_builder import _build_default_providers
    providers, screener, nse, gdelt = _build_default_providers(market)
    return ContextBuilder(
        providers, screener=screener, nse=nse, gdelt=gdelt, mode_config=mode_config,
    )


def _sanitize_for_checkpoint(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize_for_checkpoint(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_checkpoint(v) for v in obj]
    if type(obj) in (int, float, bool, str, bytes) or obj is None:
        return obj
    item_attr = getattr(obj, "item", None)
    if callable(item_attr):
        try:
            converted = item_attr()
        except (TypeError, ValueError):
            return obj
        if converted is obj:
            return obj
        return _sanitize_for_checkpoint(converted)
    return obj


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

async def _smoke_test(query: str = "Analyze RELIANCE") -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _force_utf8_stdout()

    from packages.agents.llm_provider import is_any_llm_configured

    has_key = is_any_llm_configured()
    if not has_key:
        print("[note] No LLM API key set - all LLM calls use templated fallbacks.\n")

    orch = Orchestrator()
    print(f"Running orchestrator on query: {query!r}")
    t0    = time.perf_counter()
    state = await orch.arun(query)
    elapsed = time.perf_counter() - t0
    print(f"Total wall time: {elapsed:.2f}s\n")

    print("=== Parsed query ===")
    print(f"  ticker: {state.get('ticker')}")
    print(f"  market: {state.get('market')}")

    ctx = state.get("context", {}) or {}
    print(f"\n=== Context ({len(ctx)} keys) ===")
    if ctx:
        keys   = sorted(ctx.keys())
        head   = ", ".join(keys[:20])
        suffix = " ..." if len(keys) > 20 else ""
        print(f"  {head}{suffix}")
    else:
        print("  (empty)")

    print("\n=== Decision ===")
    decision = state.get("decision")
    if decision is not None:
        print(decision.model_dump_json(indent=2))
    else:
        print("  (no decision emitted)")

    print("\n=== Reasoning trace ===")
    for step in state.get("reasoning_trace", []) or []:
        ms = f"{step.duration_ms:.0f}ms" if step.duration_ms is not None else "  -  "
        print(f"  [{step.node:14s}] {step.summary}  ({ms})")

    if state.get("error"):
        print(f"\n[error] {state['error']}")
    return 0


def _main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Run the agent orchestrator end-to-end.")
    parser.add_argument(
        "query", nargs="?", default="Analyze RELIANCE",
        help='Free-text query, e.g. "Should I buy INFY?"',
    )
    args = parser.parse_args()
    return asyncio.run(_smoke_test(args.query))


if __name__ == "__main__":
    raise SystemExit(_main())

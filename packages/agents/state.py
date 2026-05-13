"""LangGraph state schema for the multi-agent orchestrator.

Each pipeline node receives an ``AgentState`` dict and returns a *partial* dict
of just the keys it wants to update. LangGraph applies field-level reducers
(the ``Annotated[..., add]`` markers below) when merging parallel branches —
that's how five analysts can write into ``reasoning_trace`` simultaneously
without losing events. Without those reducers the second writer triggers
``InvalidUpdateError`` at fan-in.

``total=False`` lets nodes return only the keys they touch; the rest of the
state passes through unchanged.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal, TypedDict

from packages.core.rule_evaluator import EvaluationResult
from packages.shared.schemas import (
    AnalystReport,
    BearCase,
    BullCase,
    Decision,
    Judgment,
    Mode,
    ReasoningStep,
)


class AgentState(TypedDict, total=False):
    # ---- input ----------------------------------------------------------
    query: str
    ticker: str
    market: Literal["IN", "US"]
    # Run mode (intraday / short_term / long_term). Drives analyst
    # activation in the graph and the category-weight override fed into
    # ``RuleEvaluator``. Defaults to ``long_term`` upstream so callers
    # that don't set the field reproduce the pre-mode behaviour exactly.
    mode: Mode

    # ---- assembled by ContextBuilder ------------------------------------
    context: dict[str, Any]

    # ---- per-pillar analyst outputs (parallel writes, distinct keys) ----
    fundamental_report: AnalystReport | None
    technical_report: AnalystReport | None
    sentiment_report: AnalystReport | None
    macro_report: AnalystReport | None
    risk_report: AnalystReport | None

    # ---- debate node output ---------------------------------------------
    bull_case: BullCase | None
    bear_case: BearCase | None

    # ---- RAG retrieval (list reducer to allow multiple appenders) -------
    retrieved_rules: Annotated[list[dict[str, Any]], add]

    # ---- judge + decision -----------------------------------------------
    evaluation: EvaluationResult | None
    judgment: Judgment | None
    decision: Decision | None

    # ---- audit trail (every node appends; reducer required) -------------
    reasoning_trace: Annotated[list[ReasoningStep], add]
    error: str | None

    # ---- run-time config (set by Orchestrator.arun, not user-facing) ----
    auto_approve_strong: bool

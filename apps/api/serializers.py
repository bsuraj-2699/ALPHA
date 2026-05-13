"""AgentState -> JSON-serializable dict converters.

The orchestrator's ``AgentState`` mixes Pydantic models (AnalystReport,
Decision, Judgment, ReasoningStep, BullCase, BearCase), a dataclass
(EvaluationResult), plain dicts, and primitives. Anything that crosses
the API boundary needs to become JSON-friendly first.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, date
from enum import Enum
from typing import Any


def _to_jsonable(value: Any) -> Any:
    """Recursively convert to JSON-friendly Python primitives.

    Pydantic models go through ``model_dump(mode='json')`` so datetimes /
    Enums / Decimals become strings up front. Dataclasses go through
    ``asdict`` and we recurse over the result to handle nested datetimes.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    # Fallback: stringify exotic objects (numpy scalars are already
    # sanitized upstream, but defensively handle anything else).
    return str(value)


# Top-level state keys we expose via ``GET /api/runs/{run_id}``. Everything
# else (e.g. ``query``, internal ``error`` strings) is filtered out so the
# response shape is stable.
_PUBLIC_KEYS = {
    "ticker",
    "market",
    "context",
    "fundamental_report",
    "technical_report",
    "sentiment_report",
    "macro_report",
    "risk_report",
    "bull_case",
    "bear_case",
    "evaluation",
    "judgment",
    "decision",
    "reasoning_trace",
    "retrieved_rules",
    "error",
}


def serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Project an orchestrator state into the API response shape.

    Only public keys survive (see ``_PUBLIC_KEYS``). The five analyst
    reports are folded under a single ``analyst_reports`` key so the
    response shape is stable across changes to the analyst slate.
    """
    out: dict[str, Any] = {}

    for key in (
        "ticker",
        "market",
        "context",
        "bull_case",
        "bear_case",
        "evaluation",
        "judgment",
        "decision",
        "reasoning_trace",
        "retrieved_rules",
        "error",
    ):
        if key in state and state[key] is not None:
            out[key] = _to_jsonable(state[key])

    analyst_reports: dict[str, Any] = {}
    for state_key, public_name in (
        ("fundamental_report", "fundamentals"),
        ("technical_report", "technicals"),
        ("sentiment_report", "sentiment"),
        ("macro_report", "macro"),
        ("risk_report", "risk"),
    ):
        report = state.get(state_key)
        if report is not None:
            analyst_reports[public_name] = _to_jsonable(report)
    if analyst_reports:
        out["analyst_reports"] = analyst_reports

    return out


def extract_interrupt(state: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the LangGraph interrupt payload out of a state dict.

    LangGraph stores pending interrupts in the special ``__interrupt__``
    field as a tuple of ``Interrupt`` objects. We project the first one's
    ``value`` (the dict our decide node passed to ``interrupt(...)``).
    """
    raw = state.get("__interrupt__")
    if not raw:
        return None
    first = raw[0] if isinstance(raw, (list, tuple)) and raw else raw
    value = getattr(first, "value", None)
    if value is None and isinstance(first, dict):
        value = first.get("value")
    if value is None:
        return None
    return _to_jsonable(value)


__all__ = ["serialize_state", "extract_interrupt"]

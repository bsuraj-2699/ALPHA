"""Pillar-specialist analyst agents.

Every analyst inherits from :class:`packages.agents.analysts._base.BaseAnalyst`
and is responsible for one ``Pillar`` slot in ``AgentState``. Concrete
analysts are stateless w.r.t. market data — they consume the already-built
``state.context`` dict and never make outbound API calls of their own.
"""

from __future__ import annotations

from packages.agents.analysts._base import BaseAnalyst, LLMNarrator, PromptInfo
from packages.agents.analysts.fundamental import FundamentalAnalyst
from packages.agents.analysts.macro import MacroAnalyst
from packages.agents.analysts.risk import RiskAnalyst
from packages.agents.analysts.sentiment import SentimentAnalyst
from packages.agents.analysts.technical import TechnicalAnalyst

__all__ = [
    "BaseAnalyst",
    "LLMNarrator",
    "PromptInfo",
    "FundamentalAnalyst",
    "TechnicalAnalyst",
    "SentimentAnalyst",
    "MacroAnalyst",
    "RiskAnalyst",
]

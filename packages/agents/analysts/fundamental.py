"""Fundamental analyst: earnings, profitability, balance-sheet health.

Owns rule categories ``fundamentals`` and ``balance_sheet`` per the
framework's "Fundamentals" composite block. The deterministic score is the
arithmetic mean of those two category scores (matching ``_composite_score``
in :mod:`packages.core.rule_evaluator`).
"""

from __future__ import annotations

from typing import ClassVar

from packages.agents.analysts._base import BaseAnalyst
from packages.shared.schemas import Pillar


class FundamentalAnalyst(BaseAnalyst):
    pillar: ClassVar[Pillar] = "fundamentals"
    categories: ClassVar[tuple[str, ...]] = ("fundamentals", "balance_sheet")

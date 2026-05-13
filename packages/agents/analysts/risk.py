"""Risk analyst: beta, volatility, guidance trend, concentration.

Owns the single rule category ``risk``. Single-category default aggregator
(mean over active categories) reduces to that one score.
"""

from __future__ import annotations

from typing import ClassVar

from packages.agents.analysts._base import BaseAnalyst
from packages.shared.schemas import Pillar


class RiskAnalyst(BaseAnalyst):
    pillar: ClassVar[Pillar] = "risk"
    categories: ClassVar[tuple[str, ...]] = ("risk",)

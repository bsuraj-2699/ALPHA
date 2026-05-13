"""Technical analyst: trend structure + momentum oscillators.

Owns rule categories ``trend`` and ``momentum``. The deterministic score uses
the framework-correct blend ``trend * 0.625 + momentum * 0.375`` rather than
a flat mean — same formula ``_composite_score`` applies for the technicals
composite block.
"""

from __future__ import annotations

from typing import ClassVar

from packages.agents.analysts._base import BaseAnalyst
from packages.core.rule_evaluator import PillarEvaluation
from packages.shared.schemas import Pillar


class TechnicalAnalyst(BaseAnalyst):
    pillar: ClassVar[Pillar] = "technicals"
    categories: ClassVar[tuple[str, ...]] = ("trend", "momentum")

    def aggregate(
        self,
        per_category_scores: dict[str, float],
        evaluation: PillarEvaluation,
    ) -> float:
        # Default to 50.0 if a sub-category had no rules — same neutral
        # fallback the deterministic engine uses.
        trend = per_category_scores.get("trend", 50.0)
        momentum = per_category_scores.get("momentum", 50.0)
        return trend * 0.625 + momentum * 0.375

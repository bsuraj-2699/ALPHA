"""Sentiment analyst: market perception + valuation.

Owns rule categories ``sentiment`` (analyst recs, insider tx, news, short
interest, institutional flow) and ``valuation`` (PE / PEG / EV-EBITDA / P-B
relative to peers). Both reflect the market's pricing of the stock vs its
intrinsic value, which is why we group them under one analyst rather than
splitting valuation into its own (the user-spec'd analyst slate is five
slots; valuation is the natural merge target with sentiment).

Aggregate score is a weighted mean using the framework's pillar weights
(sentiment 0.15, valuation 0.18) so the analyst's number is consistent with
the eventual composite weighting.
"""

from __future__ import annotations

from typing import ClassVar

from packages.agents.analysts._base import BaseAnalyst
from packages.core.rule_evaluator import PillarEvaluation
from packages.shared.schemas import Pillar


class SentimentAnalyst(BaseAnalyst):
    pillar: ClassVar[Pillar] = "sentiment"
    categories: ClassVar[tuple[str, ...]] = ("sentiment", "valuation")

    # Framework pillar weights, normalized.
    _SENTIMENT_W: ClassVar[float] = 0.15
    _VALUATION_W: ClassVar[float] = 0.18

    def aggregate(
        self,
        per_category_scores: dict[str, float],
        evaluation: PillarEvaluation,
    ) -> float:
        sent = per_category_scores.get("sentiment", 50.0)
        val = per_category_scores.get("valuation", 50.0)
        total = self._SENTIMENT_W + self._VALUATION_W
        return (sent * self._SENTIMENT_W + val * self._VALUATION_W) / total

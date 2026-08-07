"""Calibrated confidence for a trade setup.

The legacy system exposed ``confidence == composite_score`` — a tautology
(the score that *defines* the signal was also its "confidence"). This module
replaces that with an evidence-quality estimate of **P(the setup is
reliable)**, independent of trade direction, decomposed into auditable axes:

    * data_coverage        — fraction of in-scope rules that had real data
    * rule_agreement       — do the fired directional rules point one way?
    * pillar_agreement     — do the active pillars agree with the composite?
    * indicator_agreement  — do the core technical indicators agree?
    * regime_confidence    — does the market regime support the direction?
    * rule_consistency      — do overrides / skips undercut the score?
    * historical_success   — hit-rate of similar historical setups (RAG)

Design notes
------------
* Deterministic and LLM-free — same inputs, same confidence. The LLM never
  touches this number (it only narrates it).
* It **converges to the composite** when coverage is full and every axis
  agrees (max conviction), and **diverges downward** on thin or conflicting
  data — which is exactly the honest behaviour the audit asked for.
* Axes with no available evidence (e.g. no historical memories, or a pillar
  with no technicals) are *dropped and their weight renormalised* so absence
  of evidence neither inflates nor deflates the result.
* ``historical_*`` inputs are optional; when the RAG market-memory layer is
  wired in (intraday) it passes a hit-rate + similarity, otherwise the axis
  is simply absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Base weights for each evidence axis (before renormalisation over the axes
# that actually have evidence for a given run). They express relative
# importance, not absolute magnitude.
_BASE_WEIGHTS: dict[str, float] = {
    "data_coverage": 0.20,
    "rule_agreement": 0.22,
    "pillar_agreement": 0.16,
    "indicator_agreement": 0.12,
    "regime_confidence": 0.08,
    "rule_consistency": 0.10,
    "historical_success": 0.12,
}

# Technical-indicator context fields consulted for indicator_agreement.
# Each maps to a small helper that returns +1 (bullish), -1 (bearish) or
# 0 (neutral / unavailable) given the context dict.
_NEUTRAL = 0.5


@dataclass
class ConfidenceBreakdown:
    """Auditable decomposition of a confidence score (all axes 0..1)."""

    confidence: float                       # final 0..100
    composite_score: float                  # signal strength that seeded it
    edge: float                             # |composite-50|/50, 0..1
    axes: dict[str, float] = field(default_factory=dict)          # axis -> 0..1 value
    weights: dict[str, float] = field(default_factory=dict)        # axis -> renormalised weight
    evidence_quality: float = 0.0           # weighted mean of axes, 0..1
    n_historical: int = 0                   # similar setups considered
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 1),
            "composite_score": round(self.composite_score, 1),
            "edge": round(self.edge, 3),
            "evidence_quality": round(self.evidence_quality, 3),
            "n_historical": self.n_historical,
            "axes": {k: round(v, 3) for k, v in self.axes.items()},
            "weights": {k: round(v, 3) for k, v in self.weights.items()},
            "notes": list(self.notes),
        }


def _sign(score: float) -> int:
    """Direction of a 0..100 score around the neutral midpoint."""
    if score > 55.0:
        return 1
    if score < 45.0:
        return -1
    return 0


def _rule_agreement(evaluation: Any, direction: int) -> tuple[float | None, list[str]]:
    """Fraction of fired, directional rules that agree with ``direction``."""
    notes: list[str] = []
    results = getattr(evaluation, "pillar_details", None)
    rules: list[Any] = []
    if results:
        for pr in results:
            rules.extend(getattr(pr, "rule_results", []) or [])
    if not rules:
        return None, notes
    directional = [r for r in rules if not getattr(r, "skipped", False) and _sign(r.score) != 0]
    if not directional:
        return None, notes
    if direction == 0:
        # No composite edge: agreement is really "how balanced" — reward
        # balance (a genuine HOLD) rather than punish it.
        bull = sum(1 for r in directional if _sign(r.score) > 0)
        bear = len(directional) - bull
        bal = 1.0 - abs(bull - bear) / max(1, len(directional))
        return bal, notes
    agree = sum(1 for r in directional if _sign(r.score) == direction)
    frac = agree / len(directional)
    if frac < 0.6:
        notes.append(f"only {agree}/{len(directional)} fired rules agree with the signal")
    return frac, notes


def _pillar_agreement(pillar_scores: dict[str, float], direction: int) -> float | None:
    active = [s for s in pillar_scores.values() if s is not None]
    directional = [s for s in active if _sign(s) != 0]
    if not directional:
        return None
    if direction == 0:
        bull = sum(1 for s in directional if _sign(s) > 0)
        bear = len(directional) - bull
        return 1.0 - abs(bull - bear) / max(1, len(directional))
    agree = sum(1 for s in directional if _sign(s) == direction)
    return agree / len(directional)


def _indicator_agreement(ctx: dict[str, Any], direction: int) -> float | None:
    """Agreement of the core technical indicators with the signal direction."""
    if direction == 0:
        return None
    votes: list[int] = []

    def add(v: int | None) -> None:
        if v is not None and v != 0:
            votes.append(v)

    # RSI-14: >55 bullish, <45 bearish.
    rsi = ctx.get("rsi_14")
    if isinstance(rsi, (int, float)):
        add(1 if rsi >= 55 else -1 if rsi <= 45 else 0)
    # MACD histogram / line vs signal.
    macd = ctx.get("macd_histogram")
    if isinstance(macd, (int, float)):
        add(1 if macd > 0 else -1 if macd < 0 else 0)
    # Trend structure: price vs long MA / golden cross.
    ma50, ma200 = ctx.get("sma_50"), ctx.get("sma_200")
    price = ctx.get("current_price")
    if isinstance(ma50, (int, float)) and isinstance(ma200, (int, float)):
        add(1 if ma50 > ma200 else -1 if ma50 < ma200 else 0)
    elif isinstance(price, (int, float)) and isinstance(ma200, (int, float)):
        add(1 if price > ma200 else -1)
    # ADX-weighted trend direction (di+ vs di-).
    di_p, di_m = ctx.get("di_plus"), ctx.get("di_minus")
    if isinstance(di_p, (int, float)) and isinstance(di_m, (int, float)):
        add(1 if di_p > di_m else -1)
    # Relative strength vs market.
    rs = ctx.get("stock_return_3m_pct")
    mk = ctx.get("market_return_3m_pct")
    if isinstance(rs, (int, float)) and isinstance(mk, (int, float)):
        add(1 if rs > mk else -1)

    if not votes:
        return None
    agree = sum(1 for v in votes if v == direction)
    return agree / len(votes)


def _regime_confidence(ctx: dict[str, Any], direction: int) -> float | None:
    regime = ctx.get("market_regime")
    if regime not in ("bull", "bear", "neutral"):
        return None
    if direction == 0 or regime == "neutral":
        return _NEUTRAL
    aligned = (regime == "bull" and direction > 0) or (regime == "bear" and direction < 0)
    return 0.85 if aligned else 0.25


def _rule_consistency(evaluation: Any, direction: int) -> tuple[float, list[str]]:
    """Penalise overrides that fight the score and heavy skip ratios."""
    notes: list[str] = []
    score = 1.0
    overrides = [o for o in getattr(evaluation, "overrides_triggered", []) or [] if getattr(o, "triggered", False)]
    # A sell-forcing override under a bullish composite is a real contradiction.
    for o in overrides:
        act = getattr(o, "action", "")
        if direction > 0 and act in ("FORCE_SELL", "FORCE_STRONG_SELL", "PAUSE_BUY", "BLOCK_BUY"):
            score -= 0.35
            notes.append(f"override {getattr(o,'override_id','?')} contradicts a bullish score")
    ev = getattr(evaluation, "rules_evaluated_count", 0) or 0
    sk = getattr(evaluation, "rules_skipped_count", 0) or 0
    total = ev + sk
    if total:
        skip_ratio = sk / total
        if skip_ratio > 0.5:
            score -= 0.25
            notes.append(f"{sk}/{total} in-scope rules skipped (thin data)")
        elif skip_ratio > 0.3:
            score -= 0.1
    return max(0.0, score), notes


def compute_confidence(
    evaluation: Any,
    context: dict[str, Any] | None = None,
    *,
    pillar_scores: dict[str, float] | None = None,
    historical_success: float | None = None,
    historical_similarity: float | None = None,
    n_historical: int = 0,
) -> ConfidenceBreakdown:
    """Estimate P(setup is reliable) as a 0..100 confidence + breakdown.

    Args:
        evaluation: a ``RuleEvaluator.EvaluationResult`` (duck-typed).
        context: the assembled context dict (for indicator / regime axes).
        pillar_scores: optional explicit pillar scores; defaults to
            ``evaluation.pillar_scores``.
        historical_success: hit-rate (0..1) of similar historical setups from
            the RAG market-memory layer, if available.
        historical_similarity: mean similarity (0..1) of the retrieved
            memories — used to shrink the historical axis toward neutral when
            matches are weak.
        n_historical: number of similar setups considered (audit only).
    """
    ctx = context or {}
    composite = float(getattr(evaluation, "composite_score", 50.0) or 50.0)
    ps = pillar_scores if pillar_scores is not None else dict(getattr(evaluation, "pillar_scores", {}) or {})
    direction = _sign(composite)
    edge = min(1.0, abs(composite - 50.0) / 50.0)

    axes: dict[str, float] = {}
    notes: list[str] = []

    # 1. data coverage
    coverage = float(getattr(evaluation, "data_coverage_pct", 100.0) or 100.0) / 100.0
    axes["data_coverage"] = max(0.0, min(1.0, coverage))

    # 2. rule agreement
    ra, ra_notes = _rule_agreement(evaluation, direction)
    if ra is not None:
        axes["rule_agreement"] = ra
        notes.extend(ra_notes)

    # 3. pillar agreement
    pa = _pillar_agreement(ps, direction)
    if pa is not None:
        axes["pillar_agreement"] = pa

    # 4. indicator agreement
    ia = _indicator_agreement(ctx, direction)
    if ia is not None:
        axes["indicator_agreement"] = ia

    # 5. regime confidence
    rc = _regime_confidence(ctx, direction)
    if rc is not None:
        axes["regime_confidence"] = rc

    # 6. rule consistency
    cons, cons_notes = _rule_consistency(evaluation, direction)
    axes["rule_consistency"] = cons
    notes.extend(cons_notes)

    # 7. historical success (RAG). Shrink toward neutral by match strength so
    # a weak historical match cannot dominate.
    if historical_success is not None and n_historical > 0:
        sim = 0.5 if historical_similarity is None else max(0.0, min(1.0, historical_similarity))
        shrunk = _NEUTRAL + (historical_success - _NEUTRAL) * (0.4 + 0.6 * sim)
        axes["historical_success"] = max(0.0, min(1.0, shrunk))
        notes.append(f"{n_historical} similar historical setups, hit-rate {historical_success:.0%}")

    # Renormalise base weights over the axes that actually have evidence.
    active_w = {k: _BASE_WEIGHTS[k] for k in axes if k in _BASE_WEIGHTS}
    wsum = sum(active_w.values()) or 1.0
    weights = {k: w / wsum for k, w in active_w.items()}
    quality = sum(axes[k] * weights[k] for k in weights)

    # Edge factor: a genuine directional edge earns full conviction; a
    # no-edge (HOLD) setup is dampened but not zeroed. Gentle so moderate
    # BUY/SELL setups aren't crushed.
    edge_factor = 0.6 + 0.4 * edge
    confidence = 100.0 * quality * edge_factor

    return ConfidenceBreakdown(
        confidence=round(max(0.0, min(100.0, confidence)), 1),
        composite_score=composite,
        edge=edge,
        axes=axes,
        weights=weights,
        evidence_quality=quality,
        n_historical=n_historical,
        notes=notes,
    )


__all__ = ["ConfidenceBreakdown", "compute_confidence"]

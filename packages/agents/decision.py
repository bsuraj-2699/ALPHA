"""Decision agent: assembles the final ``Decision`` from a deterministic Judgment.

This module is intentionally LLM-free. Position sizing, stop-loss, target
price, and the ``requires_human_review`` flag are all derived mechanically
from the post-override signal and the assembled context. The LLM cannot
move money — it only writes prose (which lives upstream in the judge's
narrative).

Sizing table (configurable via ``DecisionAgent(position_sizing=...)``):

    STRONG_BUY   8 %  (within the 6-10 % band, capped at 10 % by OVR-O5)
    BUY          4 %  (within the 3-5 % band)
    HOLD         0 %  (no new entry — hold existing)
    SELL         2 %  (trim target per spec)
    STRONG_SELL  0 %  (full exit)

Stop-loss is set 8 % below entry for BUY / STRONG_BUY signals, mirroring
the spirit of OVR-O4 (PAUSE_BUY when price <=-8 % vs avg purchase). Target
price uses the analyst-consensus ``target_price_avg`` from the context if
present, otherwise +20 % above entry as a default upside.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from packages.shared.schemas import Decision, Judgment, Market, Mode, Signal


# Default position sizing as portfolio-percent targets keyed by signal.
# Constructor argument lets callers override (e.g. for backtests).
DEFAULT_POSITION_SIZING: dict[Signal, float] = {
    "STRONG_BUY": 8.0,
    "BUY": 4.0,
    "HOLD": 0.0,
    "SELL": 2.0,
    "STRONG_SELL": 0.0,
}

# OVR-O5 absolute cap: no single position above 10 % of portfolio.
_PORTFOLIO_CAP_PCT: float = 10.0

# OVR-O4 spirit: 8 % below entry triggers re-evaluation.
_STOP_LOSS_PCT: float = 0.08

# Default upside if no analyst consensus is present.
_DEFAULT_TARGET_UPSIDE: float = 0.20

# Below this data-coverage threshold we cap position size and tag the
# decision with a low-coverage warning. The threshold and cap come from
# PART A FIX 2 of the spec.
_LOW_COVERAGE_THRESHOLD_PCT: float = 60.0
_LOW_COVERAGE_POSITION_CAP_PCT: float = 3.0
_LOW_COVERAGE_WARNING: str = "Low data coverage — treat signal with caution"


class DecisionAgent:
    """Stateless deterministic decision builder."""

    def __init__(
        self,
        position_sizing: dict[Signal, float] | None = None,
        stop_loss_pct: float = _STOP_LOSS_PCT,
        default_target_upside: float = _DEFAULT_TARGET_UPSIDE,
    ) -> None:
        sizing = dict(DEFAULT_POSITION_SIZING)
        if position_sizing:
            sizing.update(position_sizing)
        # Enforce the absolute cap.
        for sig, pct in sizing.items():
            if pct > _PORTFOLIO_CAP_PCT:
                raise ValueError(
                    f"position_sizing[{sig}]={pct} exceeds the OVR-O5 cap of "
                    f"{_PORTFOLIO_CAP_PCT}%; refusing to construct."
                )
        self.position_sizing = sizing
        self.stop_loss_pct = stop_loss_pct
        self.default_target_upside = default_target_upside

    # ------------------------------------------------------------------

    def build(
        self,
        ticker: str,
        market: Market,
        judgment: Judgment,
        context: dict[str, Any],
        data_coverage_pct: float = 100.0,
        mode: Mode = "long_term",
    ) -> Decision:
        signal = judgment.signal
        position_size = self.position_sizing.get(signal, 0.0)
        position_size = min(position_size, _PORTFOLIO_CAP_PCT)

        # Low-coverage guardrail: when fewer than 60 % of in-scope rules
        # had data, the signal is genuinely uncertain. Cap position size
        # at 3 % regardless of signal strength and tag the decision with
        # a UI-visible warning. Stronger signals lose the most here, by
        # design — a STRONG_BUY made on thin data should not size up.
        warning: str | None = None
        if data_coverage_pct < _LOW_COVERAGE_THRESHOLD_PCT:
            position_size = min(position_size, _LOW_COVERAGE_POSITION_CAP_PCT)
            warning = _LOW_COVERAGE_WARNING

        entry_price, stop_loss, target_price = self._derive_levels(
            signal=signal,
            context=context,
        )

        return Decision(
            ticker=ticker,
            market=market,
            signal=signal,
            confidence=judgment.composite_score,
            position_size_pct=position_size,
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            rationale=judgment.narrative,
            citations=list(judgment.cited_rule_ids),
            overrides_active=list(judgment.overrides_active),
            requires_human_review=signal in ("STRONG_BUY", "STRONG_SELL"),
            data_coverage_pct=data_coverage_pct,
            warning=warning,
            mode=mode,
            timestamp=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------

    def _derive_levels(
        self,
        signal: Signal,
        context: dict[str, Any],
    ) -> tuple[float | None, float | None, float | None]:
        """Compute (entry_price, stop_loss, target_price) per the spec.

        BUY / STRONG_BUY  -> entry = current_price; stop = entry * (1 - 8%);
                            target = analyst consensus or entry * 1.20.
        HOLD              -> all three None (no new entry; existing position
                             managed elsewhere).
        SELL / STRONG_SELL-> all three None (we're exiting; no entry plan).
        """
        if signal not in ("BUY", "STRONG_BUY"):
            return None, None, None

        current_price = _to_float(context.get("current_price"))
        if current_price is None or current_price <= 0:
            # No usable entry datum; emit None rather than fabricate.
            return None, None, None

        stop_loss = round(current_price * (1.0 - self.stop_loss_pct), 4)

        target_avg = _to_float(context.get("target_price_avg"))
        if target_avg is not None and target_avg > current_price:
            target_price = round(target_avg, 4)
        else:
            target_price = round(current_price * (1.0 + self.default_target_upside), 4)

        return round(current_price, 4), stop_loss, target_price


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["DecisionAgent", "DEFAULT_POSITION_SIZING"]

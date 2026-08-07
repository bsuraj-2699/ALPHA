"""Intraday Market Memory — a RAG layer over *completed* market situations.

Purpose
-------
The original Qdrant integration was never wired into the live path (see
Investigation §9). This module gives it a real job: a persistent memory of
high-quality, completed intraday market *fingerprints* and their outcomes,
retrieved as **additional evidence** for new intraday setups.

Contract (never violated)
--------------------------
* The deterministic Rule Engine remains the sole decision maker. Retrieved
  memories NEVER change a BUY/SELL/HOLD. They only inform ``confidence``,
  the risk/quality estimate, and the human-readable explanation.
* Similarity is computed over a **numeric market fingerprint** — normalised
  technical, derivatives, breadth and regime features — not free text. This
  is faster than text embeddings (<5 ms, no model download) and semantically
  correct for comparing market states. Qdrant stores the fingerprint vector
  directly (COSINE); an in-memory fallback keeps everything testable without
  a running Qdrant.

Storage policy
--------------
Store only *high-quality completed situations* — an actionable intraday
signal (BUY/SELL/STRONG_*) that reached an outcome (PnL known). HOLDs and
skipped runs are not worth remembering. Callers enforce this via
``should_remember``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

MARKET_MEMORY_COLLECTION = "market_memory"


# ---------------------------------------------------------------------------
# Fingerprint: ordered, normalised numeric features of a market situation.
# Each entry maps a stable feature name to a function ctx -> float in ~[-1, 1]
# (or [0, 1]). Order is FROZEN — it defines the vector dimensionality. Append
# new features at the END only (older vectors keep their meaning).
# ---------------------------------------------------------------------------


def _num(ctx: dict[str, Any], key: str, default: float = 0.0) -> float:
    v = ctx.get(key)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return default


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _regime_onehot(ctx: dict[str, Any], target: str) -> float:
    return 1.0 if ctx.get("market_regime") == target else 0.0


def _trend_onehot(ctx: dict[str, Any], target: str) -> float:
    return 1.0 if ctx.get("nifty_trend") == target else 0.0


# (name, extractor) — extractor returns a normalised float.
FINGERPRINT_FEATURES: tuple[tuple[str, Callable[[dict[str, Any]], float]], ...] = (
    # --- Momentum / oscillators ---
    ("rsi_14", lambda c: _clip((_num(c, "rsi_14", 50.0) - 50.0) / 50.0)),
    ("macd_hist", lambda c: _clip(_num(c, "macd_histogram") / 5.0)),
    ("adx", lambda c: _clip(_num(c, "adx", 20.0) / 50.0, 0.0, 1.0)),
    ("di_bias", lambda c: _clip((_num(c, "di_plus") - _num(c, "di_minus")) / 50.0)),
    # --- Trend structure ---
    ("ma_cross", lambda c: 1.0 if _num(c, "sma_50") > _num(c, "sma_200") else -1.0),
    ("px_vs_ma50", lambda c: _clip((_num(c, "current_price") - _num(c, "sma_50")) / max(1e-6, _num(c, "sma_50")))),
    ("supertrend_dir", lambda c: _clip(_num(c, "supertrend_direction"))),
    # --- Volatility ---
    ("atr_pct", lambda c: _clip(_num(c, "atr_pct", _num(c, "atr")) / 10.0, 0.0, 1.0)),
    ("bb_pos", lambda c: _clip(_num(c, "bb_percent_b", 0.5) * 2.0 - 1.0)),
    ("vix", lambda c: _clip(_num(c, "vix_level", 18.0) / 40.0, 0.0, 1.0)),
    # --- Volume / VWAP ---
    ("rel_volume", lambda c: _clip(_num(c, "relative_volume", 1.0) / 3.0, 0.0, 1.0)),
    ("vwap_dist", lambda c: _clip((_num(c, "current_price") - _num(c, "vwap")) / max(1e-6, _num(c, "vwap")))
        if _num(c, "vwap") else 0.0),
    # --- Derivatives ---
    ("pcr", lambda c: _clip((_num(c, "pcr", 1.0) - 1.0))),
    ("iv", lambda c: _clip(_num(c, "iv", _num(c, "implied_volatility")) / 60.0, 0.0, 1.0)),
    ("max_pain_dist", lambda c: _clip((_num(c, "current_price") - _num(c, "max_pain")) / max(1e-6, _num(c, "max_pain")))
        if _num(c, "max_pain") else 0.0),
    ("oi_change", lambda c: _clip(_num(c, "oi_change_pct") / 50.0)),
    # --- Breadth / flows ---
    ("fii_flow", lambda c: _clip(_num(c, "fii_net_flow_cr") / 5000.0)),
    ("dii_flow", lambda c: _clip(_num(c, "dii_net_flow_cr") / 5000.0)),
    ("adv_decl", lambda c: _clip(_num(c, "advance_decline_ratio", 1.0) - 1.0)),
    ("sector_rs", lambda c: _clip((_num(c, "stock_return_3m_pct") - _num(c, "sector_return_3m_pct")) / 20.0)),
    # --- Regime / trend one-hots ---
    ("regime_bull", lambda c: _regime_onehot(c, "bull")),
    ("regime_bear", lambda c: _regime_onehot(c, "bear")),
    ("nifty_up", lambda c: _trend_onehot(c, "uptrend")),
    ("nifty_down", lambda c: _trend_onehot(c, "downtrend")),
)

FINGERPRINT_DIM = len(FINGERPRINT_FEATURES)


def fingerprint_vector(context: dict[str, Any]) -> list[float]:
    """Deterministic normalised feature vector for a market situation."""
    return [fn(context) for _name, fn in FINGERPRINT_FEATURES]


def fingerprint_text(context: dict[str, Any], ticker: str) -> str:
    """Human-readable one-line fingerprint (payload / explanation only)."""
    parts = [
        f"{ticker}",
        f"regime={context.get('market_regime', '?')}",
        f"trend={context.get('nifty_trend', '?')}",
        f"rsi={_num(context, 'rsi_14', 50):.0f}",
        f"adx={_num(context, 'adx', 0):.0f}",
        f"atr%={_num(context, 'atr_pct', 0):.2f}",
        f"pcr={_num(context, 'pcr', 0):.2f}",
        f"vix={_num(context, 'vix_level', 0):.1f}",
        f"relvol={_num(context, 'relative_volume', 0):.1f}",
    ]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Memory record
# ---------------------------------------------------------------------------


@dataclass
class MarketMemory:
    """One completed intraday market situation + its outcome."""

    memory_id: str
    ticker: str
    timestamp: str            # ISO-8601
    timeframe: str            # e.g. "5minute"
    market_regime: str
    signal: str               # BUY / SELL / STRONG_BUY / STRONG_SELL / HOLD
    composite_score: float
    confidence: float
    matched_rules: list[str] = field(default_factory=list)
    skipped_rules: list[str] = field(default_factory=list)
    overrides_active: list[str] = field(default_factory=list)
    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    exit_price: float | None = None
    pnl_pct: float | None = None
    outcome: str | None = None       # "win" | "loss" | "flat" | None (open)
    reasoning_summary: str = ""
    fingerprint: dict[str, Any] = field(default_factory=dict)  # raw feature snapshot

    def payload(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "ticker": self.ticker,
            "timestamp": self.timestamp,
            "timeframe": self.timeframe,
            "market_regime": self.market_regime,
            "signal": self.signal,
            "composite_score": self.composite_score,
            "confidence": self.confidence,
            "matched_rules": self.matched_rules,
            "skipped_rules": self.skipped_rules,
            "overrides_active": self.overrides_active,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "outcome": self.outcome,
            "reasoning_summary": self.reasoning_summary,
            "doc_type": "market_memory",
        }


@dataclass
class MemoryHit:
    id: str
    score: float          # similarity 0..1
    text: str
    metadata: dict[str, Any]


def should_remember(signal: str, pnl_pct: float | None) -> bool:
    """Store only actionable, completed situations (an outcome is known)."""
    return signal in ("BUY", "SELL", "STRONG_BUY", "STRONG_SELL") and pnl_pct is not None


def summarise_evidence(hits: list[MemoryHit]) -> dict[str, Any]:
    """Aggregate retrieved memories into a confidence-ready evidence bundle.

    ``success_rate`` weights each historical outcome by its similarity so a
    weak match counts less. Returns neutral (0.5 / n=0) when nothing useful is
    retrieved so the confidence layer's historical axis simply drops out.
    """
    scored = [h for h in hits if h.metadata.get("outcome") in ("win", "loss")]
    if not scored:
        return {"success_rate": None, "mean_similarity": 0.0, "n": 0, "cases": _cases(hits)}
    wsum = sum(h.score for h in scored) or 1.0
    wins = sum(h.score for h in scored if h.metadata.get("outcome") == "win")
    return {
        "success_rate": wins / wsum,
        "mean_similarity": sum(h.score for h in scored) / len(scored),
        "n": len(scored),
        "cases": _cases(hits),
    }


def _cases(hits: list[MemoryHit]) -> list[dict[str, Any]]:
    out = []
    for h in hits[:5]:
        m = h.metadata
        out.append({
            "memory_id": m.get("memory_id", h.id),
            "ticker": m.get("ticker"),
            "timestamp": m.get("timestamp"),
            "similarity": round(h.score, 3),
            "signal": m.get("signal"),
            "outcome": m.get("outcome"),
            "pnl_pct": m.get("pnl_pct"),
            "summary": h.text,
        })
    return out


# ---------------------------------------------------------------------------
# Store: Qdrant-backed with an in-memory fallback (both COSINE on fingerprint)
# ---------------------------------------------------------------------------


class _InMemoryIndex:
    """Tiny cosine index used when Qdrant is not configured (and in tests)."""

    def __init__(self) -> None:
        self._items: list[tuple[str, list[float], str, dict[str, Any]]] = []

    def upsert(self, mid: str, vec: list[float], text: str, payload: dict[str, Any]) -> None:
        self._items = [it for it in self._items if it[0] != mid]
        self._items.append((mid, vec, text, payload))

    def search(self, vec: list[float], limit: int, ticker: str | None) -> list[MemoryHit]:
        def cos(a: list[float], b: list[float]) -> float:
            num = sum(x * y for x, y in zip(a, b))
            da = math.sqrt(sum(x * x for x in a)) or 1e-9
            db = math.sqrt(sum(y * y for y in b)) or 1e-9
            return num / (da * db)

        cand = self._items
        if ticker:
            same = [it for it in cand if it[3].get("ticker") == ticker]
            cand = same or cand
        scored = [
            MemoryHit(id=mid, score=(cos(vec, v) + 1.0) / 2.0, text=txt, metadata=pl)
            for (mid, v, txt, pl) in cand
        ]
        scored.sort(key=lambda h: -h.score)
        return scored[:limit]

    def count(self) -> int:
        return len(self._items)


class MarketMemoryStore:
    """Persistent store of intraday market fingerprints + outcomes."""

    def __init__(
        self,
        qdrant_url: str | None = None,
        *,
        in_memory: bool = False,
        collection: str = MARKET_MEMORY_COLLECTION,
    ) -> None:
        self.collection = collection
        self._mem = _InMemoryIndex()
        self._vs: Any | None = None
        self._use_qdrant = bool(qdrant_url) and not in_memory
        if self._use_qdrant:
            try:
                from packages.rag.store import VectorStore

                self._vs = VectorStore(collection, url=qdrant_url)
                self._vs.ensure_collection(FINGERPRINT_DIM)
            except Exception as e:  # pragma: no cover - qdrant optional at runtime
                logger.warning("market memory: Qdrant unavailable (%s); using in-memory", e)
                self._use_qdrant = False
                self._vs = None

    # ----- write -----------------------------------------------------------

    def remember(self, memory: MarketMemory, context: dict[str, Any]) -> None:
        vec = fingerprint_vector(context)
        text = fingerprint_text(context, memory.ticker)
        payload = memory.payload()
        payload["text"] = text
        if self._use_qdrant and self._vs is not None:
            try:
                from packages.rag.store import Chunk

                chunk = Chunk(id=memory.memory_id, text=text, metadata=memory.payload())
                self._vs.upsert([chunk], [vec])
                return
            except Exception as e:  # pragma: no cover
                logger.warning("market memory: Qdrant upsert failed (%s); using in-memory", e)
        self._mem.upsert(memory.memory_id, vec, text, payload)

    # ----- read ------------------------------------------------------------

    def recall(
        self, context: dict[str, Any], ticker: str, k: int = 5
    ) -> list[MemoryHit]:
        vec = fingerprint_vector(context)
        if self._use_qdrant and self._vs is not None:
            try:
                hits = self._vs.search(vec, limit=k, filters=None)
                return [
                    MemoryHit(id=h.id, score=_cosine_to_unit(h.score), text=h.text, metadata=h.metadata)
                    for h in hits
                ]
            except Exception as e:  # pragma: no cover
                logger.warning("market memory: Qdrant search failed (%s); using in-memory", e)
        return self._mem.search(vec, k, ticker)

    def count(self) -> int:
        if self._use_qdrant and self._vs is not None:
            try:
                return self._vs.count()
            except Exception:  # pragma: no cover
                return 0
        return self._mem.count()


def _cosine_to_unit(score: float) -> float:
    """Qdrant COSINE score is already in [-1,1]; map to [0,1] like the fallback."""
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


class MarketMemoryRetriever:
    """Adapter exposing ``recall`` as a fingerprint-based evidence lookup.

    Kept separate from the rules ``HybridRetriever`` (which the judge uses for
    rule citations) — this one compares *market states*, not text.
    """

    def __init__(self, store: MarketMemoryStore, top_k: int = 5) -> None:
        self.store = store
        self.top_k = top_k

    def retrieve_evidence(self, context: dict[str, Any], ticker: str) -> dict[str, Any]:
        hits = self.store.recall(context, ticker, self.top_k)
        return summarise_evidence(hits)


__all__ = [
    "MARKET_MEMORY_COLLECTION",
    "FINGERPRINT_DIM",
    "FINGERPRINT_FEATURES",
    "MarketMemory",
    "MemoryHit",
    "MarketMemoryStore",
    "MarketMemoryRetriever",
    "fingerprint_vector",
    "fingerprint_text",
    "should_remember",
    "summarise_evidence",
]

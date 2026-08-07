"""Unit tests for the intraday market-memory RAG layer.

No Qdrant / embedding model required — the in-memory fingerprint index runs
everywhere. Verifies (1) similar market states retrieve the right memories,
(2) outcomes aggregate into confidence-ready evidence, and (3) the store
never needs a network service to be useful.
"""

from __future__ import annotations

from packages.rag.market_memory import (
    FINGERPRINT_DIM,
    MarketMemory,
    MarketMemoryRetriever,
    MarketMemoryStore,
    fingerprint_vector,
    should_remember,
    summarise_evidence,
)


def _bullish_ctx() -> dict:
    return {
        "rsi_14": 68, "macd_histogram": 2.5, "adx": 32, "di_plus": 30, "di_minus": 12,
        "sma_50": 110, "sma_200": 100, "current_price": 115, "supertrend_direction": 1,
        "atr_pct": 1.2, "bb_percent_b": 0.8, "vix_level": 14, "relative_volume": 2.1,
        "vwap": 112, "pcr": 0.7, "iv": 18, "max_pain": 110, "oi_change_pct": 12,
        "fii_net_flow_cr": 2500, "dii_net_flow_cr": 800, "advance_decline_ratio": 1.6,
        "stock_return_3m_pct": 14, "sector_return_3m_pct": 6,
        "market_regime": "bull", "nifty_trend": "uptrend",
    }


def _bearish_ctx() -> dict:
    return {
        "rsi_14": 32, "macd_histogram": -2.2, "adx": 28, "di_plus": 11, "di_minus": 29,
        "sma_50": 95, "sma_200": 105, "current_price": 90, "supertrend_direction": -1,
        "atr_pct": 2.4, "bb_percent_b": 0.15, "vix_level": 26, "relative_volume": 1.8,
        "vwap": 93, "pcr": 1.4, "iv": 34, "max_pain": 98, "oi_change_pct": -18,
        "fii_net_flow_cr": -3000, "dii_net_flow_cr": -400, "advance_decline_ratio": 0.5,
        "stock_return_3m_pct": -12, "sector_return_3m_pct": -3,
        "market_regime": "bear", "nifty_trend": "downtrend",
    }


def test_fingerprint_vector_is_fixed_dim() -> None:
    v = fingerprint_vector(_bullish_ctx())
    assert len(v) == FINGERPRINT_DIM
    assert all(-1.0001 <= x <= 1.0001 for x in v)


def test_similar_state_retrieves_matching_memory() -> None:
    store = MarketMemoryStore(in_memory=True)
    store.remember(
        MarketMemory(
            memory_id="bull-win-1", ticker="RELIANCE", timestamp="2026-01-05T10:00:00Z",
            timeframe="5minute", market_regime="bull", signal="BUY",
            composite_score=72, confidence=68, outcome="win", pnl_pct=3.1,
        ),
        _bullish_ctx(),
    )
    store.remember(
        MarketMemory(
            memory_id="bear-loss-1", ticker="RELIANCE", timestamp="2026-01-06T10:00:00Z",
            timeframe="5minute", market_regime="bear", signal="SELL",
            composite_score=28, confidence=64, outcome="loss", pnl_pct=-2.4,
        ),
        _bearish_ctx(),
    )
    assert store.count() == 2

    # A fresh bullish situation should surface the bullish memory first.
    hits = store.recall(_bullish_ctx(), "RELIANCE", k=2)
    assert hits[0].metadata["memory_id"] == "bull-win-1"
    assert hits[0].score > hits[1].score


def test_evidence_aggregation_weights_by_similarity() -> None:
    store = MarketMemoryStore(in_memory=True)
    # Two bullish wins + one bullish loss → success_rate should be > 0.5.
    for i, (out, pnl) in enumerate([("win", 2.0), ("win", 1.5), ("loss", -1.0)]):
        store.remember(
            MarketMemory(
                memory_id=f"m{i}", ticker="INFY", timestamp="2026-01-05T10:00:00Z",
                timeframe="5minute", market_regime="bull", signal="BUY",
                composite_score=70, confidence=65, outcome=out, pnl_pct=pnl,
            ),
            _bullish_ctx(),
        )
    ev = MarketMemoryRetriever(store, top_k=5).retrieve_evidence(_bullish_ctx(), "INFY")
    assert ev["n"] == 3
    assert ev["success_rate"] is not None and ev["success_rate"] > 0.5
    assert 0.0 <= ev["mean_similarity"] <= 1.0
    assert len(ev["cases"]) == 3


def test_should_remember_policy() -> None:
    assert should_remember("BUY", 3.0) is True
    assert should_remember("STRONG_SELL", -2.0) is True
    assert should_remember("HOLD", 1.0) is False        # not actionable
    assert should_remember("BUY", None) is False        # no outcome yet


def test_empty_recall_is_neutral() -> None:
    store = MarketMemoryStore(in_memory=True)
    ev = summarise_evidence(store.recall(_bullish_ctx(), "TCS", k=5))
    assert ev["n"] == 0
    assert ev["success_rate"] is None

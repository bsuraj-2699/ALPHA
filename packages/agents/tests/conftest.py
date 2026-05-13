"""Shared fixtures for orchestrator-level tests.

The fixtures here cover full-graph scenarios. Fixtures for unit-testing
individual analysts live alongside their tests in
``packages/agents/analysts/tests/conftest.py``.
"""

from __future__ import annotations

from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Fake ContextBuilder — duck-typed shim so end-to-end tests don't need yfinance
# ---------------------------------------------------------------------------


class StubContextBuilder:
    """Minimal stand-in for ``ContextBuilder``. Implements the only method the
    orchestrator's context_build node calls: ``async build(ticker, market) ->
    dict``. Returns a defensive copy each time."""

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = dict(context)

    async def build(self, ticker: str, market: str) -> dict[str, Any]:  # noqa: ARG002
        return dict(self._context)


# ---------------------------------------------------------------------------
# Synthetic contexts
# ---------------------------------------------------------------------------


def _base_us_context() -> dict[str, Any]:
    """A US-market context where rules across all pillars have inputs.

    Mostly bullish-leaning so without overrides the composite would land
    >50; that's what makes the FRAUDCO test meaningful (override flips an
    otherwise-decent signal to STRONG_SELL).
    """
    return {
        "market": "US",
        "sector": "technology",
        "stock_sector": "technology",
        "stock_sector_classification": "cyclical",
        # Fundamentals
        "eps_yoy_pct": 25.0,
        "eps_qoq_pct": 5.0,
        "eps_misses_consecutive": 0,
        "revenue_yoy_pct": 18.0,
        "revenue_decline_quarters_consecutive": 0,
        "net_margin_current": 0.22,
        "net_margin_2q_ago": 0.20,
        "industry_avg_margin": 0.15,
        "roe_pct": 22.0,
        "roa_pct": 11.0,
        "fcf_yield_pct": 6.0,
        "fcf_negative_quarters_consecutive": 0,
        "is_growth_stock": True,
        "is_financial_sector": False,
        "revenue_growing": True,
        "margin_improving": True,
        "earnings_declining": False,
        # Balance sheet
        "debt_to_equity": 0.4,
        "debt_to_equity_yoy_change": -0.05,
        "debt_to_equity_change_yoy": -0.05,
        "current_ratio": 2.0,
        "quick_ratio": 1.5,
        "interest_coverage_ratio": 12.0,
        # Trend
        "current_price": 200.0,
        "ma_50": 200.0,
        "ma_200": 170.0,
        "ma_50_prev_5d": 168.0,
        "ma_200_prev_5d": 170.0,
        "high_52w": 210.0,
        "low_52w": 100.0,
        "ema_8": 201.0,
        "ema_13": 198.0,
        "ema_21": 195.0,
        "ema_34": 192.0,
        "ema_55": 188.0,
        "ribbon_compression_pct": 7.0,
        "fundamental_score": 75.0,
        # Momentum
        "rsi_14": 62.0,
        "rsi_divergence_bearish": False,
        "rsi_divergence_bullish": False,
        "macd_line": 1.8,
        "macd_signal": 0.6,
        "macd_histogram": 1.2,
        "macd_histogram_prev": 0.8,
        "stoch_k": 70.0,
        "stoch_d": 65.0,
        "stoch_k_prev": 60.0,
        "stoch_d_prev": 58.0,
        "volume_today": 1_500_000,
        "volume_avg_20d": 1_000_000,
        "volume_avg_ratio": 1.5,
        "price_change_today_pct": 2.0,
        "is_breakout": True,
        "bb_upper": 205.0,
        "bb_middle": 195.0,
        "bb_lower": 185.0,
        "bb_squeeze": False,
        "nearest_support": 190.0,
        "nearest_resistance": 210.0,
        "broke_support_today": False,
        "bounced_off_support_today": True,
        # Sentiment
        "analyst_buy_pct": 70.0,
        "insider_buy_count_3m": 5,
        "insider_sell_count_3m": 2,
        "news_sentiment_14d_avg": 0.3, 
        "negative_news_volume_spike": False,
        "fii_net_crore": 3500.0, 
        "dii_net_crore": 500.0,  
        "policy_rate_change_3m_bps": -25.0,
        "gdp_yoy_pct_prev_quarter": 2.3,
        # Valuation
        "pe_ratio": 22.0,
        "forward_pe": 20.0,
        "sector_pe_avg": 25.0,
        "peg_ratio": 1.2,
        "ev_ebitda": 15.0,
        "industry_ev_ebitda_median": 17.0,
        "pb_ratio": 4.5,
        "dividend_yield_pct": 1.0,
        "payout_ratio_pct": 25.0,
        "target_price_avg": 240.0,
        # Macro
        "policy_rate_trend": "neutral",
        "gdp_yoy_pct": 2.5,
        "cpi_yoy_pct": 2.8,
        "market_regime": "bull",
        "favorable_sectors_for_cuts": ["technology", "growth"],
        "unfavorable_sectors_for_hikes": ["technology", "growth"],
        # Risk
        "beta": 1.1,
        "vix_level": 18.0,
        "vix_change_5d_pct": -2.0,
        "guidance_trend": "raising",
    }


def _override_data_zeroed() -> dict[str, Any]:
    """Default values for override data fields. Override fast-path requires
    every key in ``data_required`` to be present even when the override
    shouldn't fire — otherwise the override engine skips it as 'missing data'.
    """
    return {
        # OVR-O1 (fraud)
        "has_fraud_allegation": False,
        "has_material_restatement": False,
        "has_sec_sebi_investigation": False,
        # OVR-O2 (guidance withdrawn)
        "guidance_withdrawn_mid_year": False,
        "guidance_withdrawal_explained": True,
        # OVR-O3 (dividend cut on declining earnings)
        "dividend_cut_announced": False,
        # OVR-O4 (stop-loss)
        "price_vs_avg_purchase_price_pct": 0.0,
        # OVR-O5 (concentration cap)
        "position_pct_of_portfolio": 0.0,
    }


@pytest.fixture
def healthy_context() -> dict[str, Any]:
    """Bullish-leaning US context with all override-data fields present and
    set to non-triggering values. Without overrides this should produce a
    BUY-leaning composite."""
    ctx = _base_us_context()
    ctx.update(_override_data_zeroed())
    return ctx


@pytest.fixture
def fraudco_context(healthy_context) -> dict[str, Any]:
    """Healthy fundamentals + fraud allegation -> OVR-O1 should fire and force
    STRONG_SELL regardless of how strong the rest of the data looks."""
    ctx = dict(healthy_context)
    ctx["has_fraud_allegation"] = True
    return ctx


@pytest.fixture
def stub_builder_factory():
    """Factory: ``stub_builder_factory(context)`` -> ``StubContextBuilder``."""

    def _factory(context: dict[str, Any]) -> StubContextBuilder:
        return StubContextBuilder(context)

    return _factory

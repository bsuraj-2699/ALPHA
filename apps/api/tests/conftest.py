"""Shared API test fixtures.

The fixtures here construct a FastAPI app whose orchestrator runs against a
synthetic context (no yfinance / Anthropic / Redis / Postgres). Tests get
an ``httpx.AsyncClient`` already plumbed through the lifespan so route
tests can ``await client.post(...)`` directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from apps.api.config import Settings
from apps.api.main import create_app


# ---------------------------------------------------------------------------
# Stub context builder
# ---------------------------------------------------------------------------


class StubContextBuilder:
    """Minimal stand-in for the production ``ContextBuilder`` so tests don't
    hit yfinance / Finnhub / FRED / GDELT.

    Returns the configured context dict regardless of (ticker, market). The
    fixtures below populate it with rule-data covering all five pillars so
    the analyst nodes can score deterministically.
    """

    def __init__(self, context: dict[str, Any]) -> None:
        self._context = dict(context)

    async def build(self, ticker: str, market: str) -> dict[str, Any]:  # noqa: ARG002
        return dict(self._context)


# ---------------------------------------------------------------------------
# Synthetic contexts (parallels the agent-suite fixtures, kept independent
# so the API suite stays self-contained).
# ---------------------------------------------------------------------------


def _override_data_zeroed() -> dict[str, Any]:
    return {
        # OVR-O1 (fraud) — present but false
        "has_fraud_allegation": False,
        "has_material_restatement": False,
        "has_sec_sebi_investigation": False,
        # OVR-O2 (guidance withdrawn)
        "guidance_withdrawn_mid_year": False,
        "guidance_withdrawal_explained": True,
        # OVR-O3 (dividend cut)
        "dividend_cut_announced": False,
        # OVR-O4 (stop-loss)
        "price_vs_avg_purchase_price_pct": 0.0,
        # OVR-O5 (concentration)
        "position_pct_of_portfolio": 0.0,
    }


def _bullish_us_ctx() -> dict[str, Any]:
    """Bullish-leaning US context with all override-data fields zeroed."""
    return {
        "market": "US",
        "sector": "technology",
        "stock_sector": "technology",
        "stock_sector_classification": "cyclical",
        # Fundamentals
        "eps_yoy_pct": 25.0,
        "revenue_yoy_pct": 18.0,
        "net_margin_current": 0.22,
        "net_margin_2q_ago": 0.20,
        "industry_avg_margin": 0.15,
        "roe_pct": 22.0,
        "roa_pct": 11.0,
        "fcf_yield_pct": 6.0,
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
        # Momentum
        "rsi_14": 62.0,
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
        "is_breakout": True,
        "bb_upper": 205.0,
        "bb_middle": 195.0,
        "bb_lower": 185.0,
        "bb_squeeze": False,
        "nearest_support": 190.0,
        "nearest_resistance": 210.0,
        "broke_support_today": False,
        "bounced_off_support_today": True,
        # Sentiment / valuation
        "analyst_buy_pct": 70.0,
        "insider_buy_count_3m": 5,
        "insider_sell_count_3m": 2,
        "news_sentiment_14d": 0.3,
        "negative_news_volume_spike": False,
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


@pytest.fixture
def healthy_context() -> dict[str, Any]:
    ctx = _bullish_us_ctx()
    ctx.update(_override_data_zeroed())
    return ctx


@pytest.fixture
def fraudco_context(healthy_context) -> dict[str, Any]:
    ctx = dict(healthy_context)
    ctx["has_fraud_allegation"] = True
    return ctx


# ---------------------------------------------------------------------------
# App + client
# ---------------------------------------------------------------------------


def _test_settings() -> Settings:
    """Settings tuned for tests: nothing external, interrupt enabled so the
    human-in-the-loop tests can exercise approve()."""
    return Settings(
        database_url="",
        redis_url="",
        qdrant_url="",
        auto_approve_strong_signals=False,
        idempotency_ttl_hours=24,
        sse_keepalive_seconds=15,
    )


def _auto_approve_settings() -> Settings:
    return Settings(
        database_url="",
        redis_url="",
        qdrant_url="",
        auto_approve_strong_signals=True,
        idempotency_ttl_hours=24,
        sse_keepalive_seconds=15,
    )


@pytest_asyncio.fixture
async def client_with_healthy_ctx(
    healthy_context,
) -> AsyncIterator[AsyncClient]:
    async for c in _make_client(_auto_approve_settings(), healthy_context):
        yield c


@pytest_asyncio.fixture
async def client_with_fraudco_ctx(
    fraudco_context,
) -> AsyncIterator[AsyncClient]:
    async for c in _make_client(_auto_approve_settings(), fraudco_context):
        yield c


@pytest_asyncio.fixture
async def client_fraudco_interrupt_mode(
    fraudco_context,
) -> AsyncIterator[AsyncClient]:
    """Same FRAUDCO context but ``auto_approve_strong_signals=False`` so the
    decide node hits the human-in-the-loop interrupt."""
    async for c in _make_client(_test_settings(), fraudco_context):
        yield c


async def _make_client(
    settings: Settings, ctx: dict[str, Any]
) -> AsyncIterator[AsyncClient]:
    app = create_app(
        settings=settings,
        context_builder=StubContextBuilder(ctx),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            ac.app = app  # type: ignore[attr-defined]
            yield ac

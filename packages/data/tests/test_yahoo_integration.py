"""Live Yahoo integration tests. Run with: pytest -m integration

The `data_required` set we expect to populate from yfinance + computed
technicals is captured in EXPECTED_FIELDS below. We assert ≥80% coverage.
"""

from __future__ import annotations

import pytest

# Fields a healthy Yahoo round-trip + technicals computation should populate.
# Excluded on purpose (Phase 3): insider_*, news_sentiment_*, macro_*, beta,
# vix_*, target_price_*, analyst upgrades/downgrades, guidance, fraud flags.
EXPECTED_FIELDS = {
    # Fundamentals (yfinance.info)
    "eps_yoy_pct",
    "revenue_yoy_pct",
    "net_margin_current",
    "roe_pct",
    "roa_pct",
    "fcf_yield_pct",
    "debt_to_equity",
    "current_ratio",
    "quick_ratio",
    "pe_ratio",
    "forward_pe",
    "ev_ebitda",
    "pb_ratio",
    "sector",
    "is_growth_stock",
    "is_financial_sector",
    "revenue_growing",
    # Technicals (computed from OHLC)
    "current_price",
    "high_52w",
    "low_52w",
    "ma_50",
    "ma_200",
    "ma_50_prev_5d",
    "ma_200_prev_5d",
    "ema_8",
    "ema_55",
    "rsi_14",
    "macd_line",
    "macd_signal",
    "macd_histogram",
    "stoch_k",
    "stoch_d",
    "bb_upper",
    "bb_lower",
    "volume_today",
    "volume_avg_20d",
    "nearest_support",
    "nearest_resistance",
}


@pytest.fixture
def yahoo(yfinance_available):  # type: ignore[no-untyped-def]
    if not yfinance_available:
        pytest.skip("yfinance not installed")
    from packages.data.providers.yahoo import YahooFinanceProvider

    return YahooFinanceProvider()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_get_quote_aapl(yahoo):  # type: ignore[no-untyped-def]
    q = await yahoo.get_quote("AAPL", "US")
    assert q.ticker == "AAPL"
    assert q.market == "US"
    assert float(q.price) > 0
    assert q.currency == "USD"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_get_fundamentals_aapl(yahoo):  # type: ignore[no-untyped-def]
    f = await yahoo.get_fundamentals("AAPL", "US")
    assert f.ticker == "AAPL"
    assert f.sector is not None
    assert f.pe_ratio is not None and f.pe_ratio > 0
    assert f.roe_pct is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_yahoo_indian_ticker_normalization(yahoo):  # type: ignore[no-untyped-def]
    """Bare 'RELIANCE' must route to RELIANCE.NS on Yahoo."""
    q = await yahoo.get_quote("RELIANCE", "IN")
    assert q.market == "IN"
    assert q.currency in ("INR", "USD")  # yfinance occasionally returns USD


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_coverage_aapl():  # type: ignore[no-untyped-def]
    from packages.data.context_builder import ContextBuilder
    from packages.data.providers.yahoo import YahooFinanceProvider

    pytest.importorskip("yfinance")
    pytest.importorskip("pandas")

    builder = ContextBuilder([YahooFinanceProvider()])
    ctx = await builder.build("AAPL", "US")
    populated = EXPECTED_FIELDS.intersection(ctx.keys())
    coverage = len(populated) / len(EXPECTED_FIELDS)
    missing = sorted(EXPECTED_FIELDS - populated)
    assert coverage >= 0.80, (
        f"Yahoo/AAPL coverage {coverage:.0%} below 80% threshold. Missing: {missing}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_coverage_reliance():  # type: ignore[no-untyped-def]
    from packages.data.context_builder import ContextBuilder
    from packages.data.providers.yahoo import YahooFinanceProvider

    pytest.importorskip("yfinance")
    pytest.importorskip("pandas")

    builder = ContextBuilder([YahooFinanceProvider()])
    ctx = await builder.build("RELIANCE.NS", "IN")
    populated = EXPECTED_FIELDS.intersection(ctx.keys())
    coverage = len(populated) / len(EXPECTED_FIELDS)
    missing = sorted(EXPECTED_FIELDS - populated)
    assert coverage >= 0.80, (
        f"Yahoo/RELIANCE coverage {coverage:.0%} below 80% threshold. Missing: {missing}"
    )

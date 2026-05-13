"""Shared fixtures for the per-analyst test suite.

The synthetic context dict here is intentionally rich: it fires a mix of
strong_buy / buy / sell tier rules across multiple pillars so each analyst
test sees a non-trivial score. We don't aim for every rule to fire — that
would require ~80 fields — just enough that aggregate_score deviates from
the neutral 50 default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from packages.agents.analysts._base import LLMNarrator, PromptInfo
from packages.core.rule_evaluator import RuleEvaluator
from packages.shared.schemas import AnalystNarrative

_RULES_PATH = Path(__file__).resolve().parents[3] / "core" / "rules.json"


from packages.agents.llm_provider import LLM_API_KEY_ENV_NAMES, is_any_llm_configured


@pytest.fixture
def strip_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in LLM_API_KEY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def evaluator() -> RuleEvaluator:
    return RuleEvaluator(_RULES_PATH)


@pytest.fixture
def rich_context() -> dict[str, Any]:
    """A US-market context where rules across all pillars have inputs.

    Mostly bullish-leaning (strong fundamentals, strong trend, supportive
    macro) so analyst aggregate scores land >50 — useful for asserting the
    deterministic score actually flows through, not just the default.
    """
    return {
        "market": "US",
        "sector": "technology",
        "stock_sector": "technology",
        "stock_sector_classification": "cyclical",
        # ---- Fundamentals ----
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
        # ---- Balance sheet ----
        "debt_to_equity": 0.4,
        "debt_to_equity_yoy_change": -0.05,
        "debt_to_equity_change_yoy": -0.05,
        "current_ratio": 2.0,
        "quick_ratio": 1.5,
        "interest_coverage_ratio": 12.0,
        # ---- Trend ----
        "current_price": 200.0,
        # Golden-cross setup for TREND-001
        "ma_50": 200.0,
        "ma_200": 170.0,
        "ma_50_prev_5d": 168.0,
        "ma_200_prev_5d": 170.0,
        # 52-week range for TREND-002 ((200-100)/(210-100) = 0.91 -> strong_buy)
        "high_52w": 210.0,
        "low_52w": 100.0,
        # EMA ribbon (TREND-003) — fanning upward, compression > 5
        "ema_8": 201.0,
        "ema_13": 198.0,
        "ema_21": 195.0,
        "ema_34": 192.0,
        "ema_55": 188.0,
        "ribbon_compression_pct": 7.0,
        "fundamental_score": 75.0,
        # ---- Momentum ----
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
        # ---- Sentiment ----
        "analyst_buy_pct": 70.0,
        "insider_buy_count_3m": 5,
        "insider_sell_count_3m": 2,
        "news_sentiment_14d_avg": 0.3,
        "fii_net_crore": 3500.0,
        "dii_net_crore": 500.0,
        "policy_rate_change_3m_bps": -25.0,
        "gdp_yoy_pct_prev_quarter": 2.3,
        "negative_news_volume_spike": False,
        # ---- Valuation ----
        "pe_ratio": 22.0,
        "forward_pe": 20.0,
        "sector_pe_avg": 25.0,
        "peg_ratio": 1.2,
        "ev_ebitda": 15.0,
        "industry_ev_ebitda_median": 17.0,
        "pb_ratio": 4.5,
        "dividend_yield_pct": 1.0,
        "payout_ratio_pct": 25.0,
        # ---- Macro ----
        "policy_rate_trend": "neutral",
        "gdp_yoy_pct": 2.5,
        "cpi_yoy_pct": 2.8,
        "market_regime": "bull",
        "favorable_sectors_for_cuts": ["technology", "growth"],
        "unfavorable_sectors_for_hikes": ["technology", "growth"],
        # ---- Risk ----
        "beta": 1.1,
        "vix_level": 18.0,
        "vix_change_5d_pct": -2.0,
        "guidance_trend": "raising",
    }


def make_fake_narrator(
    *,
    narrative: str = "Synthetic narrative for unit tests.",
    top_signals: list[str] | None = None,
    citations: list[str] | None = None,
    confidence: float = 0.5,
) -> LLMNarrator:
    """Inject-able narrator that ignores the prompt and returns a fixed
    ``AnalystNarrative``. The score is NOT something the narrator can
    return (schema doesn't expose it), so the analyst has nothing to clobber.
    """

    async def _narrator(prompt: str, info: PromptInfo) -> AnalystNarrative:  # noqa: ARG001
        return AnalystNarrative(
            narrative=narrative,
            top_signals=list(top_signals or []),
            citations=list(citations or []),
            confidence=confidence,
        )

    return _narrator

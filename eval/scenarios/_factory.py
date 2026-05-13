"""One-shot generator for the bundled scenario JSON files.

Why a generator? A scenario is just `baseline + a few overrides`. Storing
80 fields per scenario by hand would be both noisy and error-prone — a
typo in any pillar's field name would silently neutralise that pillar
(missing data == skipped == neutral 50). This module owns one well-tested
baseline; per-scenario overrides are short and readable.

Run with::

    python -m eval.scenarios._factory

It writes / overwrites the public ``*.json`` files in this directory.
The JSONs are committed and are the source of truth for CI - this
file just makes them less painful to maintain.

The leading underscore in the filename keeps :func:`discover_scenarios`
from picking it up as a scenario.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

OUT_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Baseline: a fully-populated, mid-range US-tech context.
# Variations override what they need; everything else stays neutral-bullish.
# ---------------------------------------------------------------------------

_BASELINE: dict[str, Any] = {
    "market": "US",
    "sector": "technology",
    "stock_sector": "technology",
    "stock_sector_classification": "cyclical",
    # Fundamentals - middling
    "eps_yoy_pct": 8.0,
    "eps_qoq_pct": 2.0,
    "eps_misses_consecutive": 0,
    "revenue_yoy_pct": 6.0,
    "revenue_decline_quarters_consecutive": 0,
    "net_margin_current": 0.18,
    "net_margin_2q_ago": 0.17,
    "industry_avg_margin": 0.15,
    "roe_pct": 14.0,
    "roa_pct": 7.0,
    "fcf_yield_pct": 3.5,
    "fcf_negative_quarters_consecutive": 0,
    "is_growth_stock": True,
    "is_financial_sector": False,
    "revenue_growing": True,
    "margin_improving": True,
    "earnings_declining": False,
    # Balance sheet - healthy
    "debt_to_equity": 0.6,
    "debt_to_equity_yoy_change": -0.02,
    "debt_to_equity_change_yoy": -0.02,
    "current_ratio": 1.8,
    "quick_ratio": 1.3,
    "interest_coverage_ratio": 12.0,
    # Trend - mildly positive
    "current_price": 150.0,
    "ma_50": 148.0,
    "ma_200": 142.0,
    "ma_50_prev_5d": 145.0,
    "ma_200_prev_5d": 142.0,
    "high_52w": 165.0,
    "low_52w": 115.0,
    "ema_8": 151.0,
    "ema_13": 149.5,
    "ema_21": 147.5,
    "ema_34": 145.0,
    "ema_55": 142.5,
    "ribbon_compression_pct": 5.6,
    "fundamental_score": 60.0,
    # Momentum - neutral-positive
    "rsi_14": 55.0,
    "rsi_divergence_bearish": False,
    "rsi_divergence_bullish": False,
    "macd_line": 0.6,
    "macd_signal": 0.4,
    "macd_histogram": 0.2,
    "macd_histogram_prev": 0.1,
    "stoch_k": 60.0,
    "stoch_d": 58.0,
    "stoch_k_prev": 55.0,
    "stoch_d_prev": 53.0,
    "volume_today": 1200000,
    "volume_avg_20d": 1000000,
    "volume_avg_ratio": 1.2,
    "price_change_today_pct": 0.8,
    "is_breakout": False,
    "bb_upper": 156.0,
    "bb_middle": 148.0,
    "bb_lower": 140.0,
    "bb_squeeze": False,
    "nearest_support": 140.0,
    "nearest_resistance": 160.0,
    "broke_support_today": False,
    "bounced_off_support_today": False,
    # Sentiment - neutral-positive (field names match rules.json exactly)
    "upgrades_30d": 1,
    "downgrades_30d": 1,
    "target_price_avg": 165.0,  # +10% upside vs current 150
    "insider_purchases_count_90d": 2,
    "insider_sales_count_90d": 2,
    "exec_holdings_pct_sold_90d": 5.0,
    "short_interest_pct_float": 4.0,
    "days_to_cover": 2.0,
    "short_interest_change_30d": 1.0,
    "has_positive_catalyst": False,
    "new_institutional_positions_qoq": 1,
    "institutional_exits_qoq": 1,
    "institutional_ownership_change_pct": 0.0,
    "news_sentiment_14d_avg": 0.05,
    "negative_news_volume_spike": False,
    # Valuation - in line
    "pe_ratio": 22.0,
    "forward_pe": 20.0,
    "sector_pe_avg": 24.0,
    "pe_5y_avg": 22.0,
    "peg_ratio": 1.5,
    "ev_ebitda": 16.0,
    "industry_ev_ebitda_median": 17.0,
    "pb_ratio": 4.0,
    "dividend_yield_pct": 1.0,
    "payout_ratio_pct": 25.0,
    "dividend_growth_5y_pct": 4.0,
    # Macro
    "policy_rate_trend": "neutral",
    "gdp_yoy_pct": 2.2,
    "cpi_yoy_pct": 3.0,
    "market_regime": "bull",
    "favorable_sectors_for_cuts": ["technology", "growth"],
    "unfavorable_sectors_for_hikes": ["technology", "growth"],
    "stock_return_3m_pct": 8.0,
    "market_return_3m_pct": 5.0,
    "sector_return_3m_pct": 7.0,
    "rs_line_at_3m_high": True,
    # Risk
    "beta": 1.05,
    "vix_level": 17.0,
    "vix_change_5d_pct": -1.0,
    "guidance_trend": "in-line",
}


def _merge(*deltas: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(_BASELINE)
    for d in deltas:
        out.update(d)
    return out


# ---------------------------------------------------------------------------
# Strong-buy variants (4)
# ---------------------------------------------------------------------------

_STRONG_BULL: dict[str, Any] = {
    # Fundamentals
    "eps_yoy_pct": 28.0,
    "eps_qoq_pct": 6.0,
    "revenue_yoy_pct": 22.0,
    "net_margin_current": 0.24,
    "net_margin_2q_ago": 0.20,
    "roe_pct": 24.0,
    "roa_pct": 12.0,
    "fcf_yield_pct": 6.0,
    "fundamental_score": 80.0,
    # Trend - golden cross with room above
    "ma_50": 160.0,
    "ma_200": 140.0,
    "ma_50_prev_5d": 138.0,
    "ma_200_prev_5d": 140.0,
    "current_price": 165.0,
    # Wide ranges so price sits high in 52w
    "high_52w": 168.0,
    "low_52w": 100.0,
    # EMA fanning + breakout
    "ema_8": 165.0,
    "ema_13": 162.0,
    "ema_21": 158.0,
    "ema_34": 152.0,
    "ema_55": 145.0,
    "ribbon_compression_pct": 7.5,
    "is_breakout": True,
    "bounced_off_support_today": True,
    # Momentum
    "rsi_14": 64.0,
    "macd_line": 1.8,
    "macd_signal": 0.6,
    "macd_histogram": 1.2,
    "macd_histogram_prev": 0.7,
    "stoch_k": 72.0,
    "stoch_d": 65.0,
    "stoch_k_prev": 60.0,
    "volume_today": 1_800_000,
    "volume_avg_20d": 1_000_000,
    "volume_avg_ratio": 1.8,
    "price_change_today_pct": 2.5,
    # Sentiment - all five rules fire BUY/STRONG_BUY tier with these
    "upgrades_30d": 4,
    "downgrades_30d": 0,
    "target_price_avg": 200.0,  # vs current 165 -> +21% upside (>1.20)
    "insider_purchases_count_90d": 4,
    "insider_sales_count_90d": 0,
    "exec_holdings_pct_sold_90d": 0.0,
    "short_interest_pct_float": 22.0,
    "days_to_cover": 12.0,
    "short_interest_change_30d": 1.0,
    "has_positive_catalyst": True,
    "new_institutional_positions_qoq": 5,
    "institutional_exits_qoq": 0,
    "institutional_ownership_change_pct": 3.5,
    "news_sentiment_14d_avg": 0.55,
    "negative_news_volume_spike": False,
    # Valuation - undervalued + growth
    "pe_ratio": 14.0,
    "sector_pe_avg": 27.0,
    "forward_pe": 12.5,
    "pe_5y_avg": 25.0,
    "peg_ratio": 0.6,
    "ev_ebitda": 9.0,
    "industry_ev_ebitda_median": 18.0,
    "dividend_growth_5y_pct": 9.0,
    # Macro / risk
    "vix_level": 16.0,
    "vix_change_5d_pct": -3.0,
    "stock_return_3m_pct": 18.0,
    "market_return_3m_pct": 6.0,
    "sector_return_3m_pct": 14.0,
}


# ---------------------------------------------------------------------------
# Bear variants
# ---------------------------------------------------------------------------

_STRONG_BEAR: dict[str, Any] = {
    # Fundamentals collapsing
    "eps_yoy_pct": -35.0,
    "eps_qoq_pct": -10.0,
    "eps_misses_consecutive": 3,
    "revenue_yoy_pct": -18.0,
    "revenue_decline_quarters_consecutive": 4,
    "net_margin_current": 0.05,
    "net_margin_2q_ago": 0.12,
    "industry_avg_margin": 0.15,
    "roe_pct": 4.0,
    "roa_pct": 1.0,
    "fcf_yield_pct": -3.0,
    "fcf_negative_quarters_consecutive": 4,
    "earnings_declining": True,
    "margin_improving": False,
    "revenue_growing": False,
    "fundamental_score": 18.0,
    # Balance sheet stretched
    "debt_to_equity": 2.6,
    "debt_to_equity_yoy_change": 0.5,
    "debt_to_equity_change_yoy": 0.5,
    "current_ratio": 0.85,
    "quick_ratio": 0.55,
    "interest_coverage_ratio": 1.6,
    # Trend - death cross, near 52w low
    "current_price": 35.0,
    "ma_50": 50.0,
    "ma_200": 65.0,
    "ma_50_prev_5d": 67.0,
    "ma_200_prev_5d": 64.0,
    "high_52w": 95.0,
    "low_52w": 32.0,
    "ema_8": 36.0,
    "ema_13": 40.0,
    "ema_21": 45.0,
    "ema_34": 52.0,
    "ema_55": 60.0,
    "ribbon_compression_pct": 14.0,
    # Momentum bearish
    "rsi_14": 28.0,
    "rsi_divergence_bearish": True,
    "macd_line": -1.5,
    "macd_signal": -0.6,
    "macd_histogram": -0.9,
    "macd_histogram_prev": -0.5,
    "stoch_k": 22.0,
    "stoch_d": 28.0,
    "stoch_k_prev": 35.0,
    "stoch_d_prev": 38.0,
    "volume_today": 4_000_000,
    "volume_avg_20d": 1_000_000,
    "volume_avg_ratio": 4.0,
    "price_change_today_pct": -6.0,
    "is_breakout": False,
    "broke_support_today": True,
    "bounced_off_support_today": False,
    "nearest_support": 36.0,
    "nearest_resistance": 55.0,
    # Sentiment - every rule fires SELL/STRONG_SELL
    "upgrades_30d": 0,
    "downgrades_30d": 5,
    "target_price_avg": 28.0,  # below current price -> downside
    "insider_purchases_count_90d": 0,
    "insider_sales_count_90d": 7,
    "exec_holdings_pct_sold_90d": 50.0,
    "short_interest_pct_float": 28.0,
    "days_to_cover": 12.0,
    "short_interest_change_30d": 12.0,
    "has_positive_catalyst": False,
    "new_institutional_positions_qoq": 0,
    "institutional_exits_qoq": 5,
    "institutional_ownership_change_pct": -8.0,
    "news_sentiment_14d_avg": -0.6,
    "negative_news_volume_spike": True,
    # Valuation - extreme overvaluation
    "pe_ratio": 95.0,
    "forward_pe": 70.0,
    "sector_pe_avg": 24.0,
    "pe_5y_avg": 30.0,
    "peg_ratio": 5.5,
    "ev_ebitda": 35.0,
    "industry_ev_ebitda_median": 17.0,
    "pb_ratio": 18.0,
    "dividend_yield_pct": 0.0,
    "payout_ratio_pct": 110.0,
    "dividend_growth_5y_pct": -5.0,
    # Macro / risk
    "vix_level": 32.0,
    "vix_change_5d_pct": 22.0,
    "stock_return_3m_pct": -38.0,
    "market_return_3m_pct": -3.0,
    "sector_return_3m_pct": -10.0,
    "rs_line_at_3m_high": False,
    "beta": 1.6,
    "guidance_trend": "lowering",
    "market_regime": "bear",
}


# ---------------------------------------------------------------------------
# Mixed / hold variants
# ---------------------------------------------------------------------------

_MIXED_NEUTRAL: dict[str, Any] = {
    # Lukewarm fundamentals
    "eps_yoy_pct": 3.0,
    "revenue_yoy_pct": 2.0,
    "net_margin_current": 0.15,
    "net_margin_2q_ago": 0.155,
    "roe_pct": 11.0,
    "fcf_yield_pct": 2.5,
    "fundamental_score": 52.0,
    # Trend sideways
    "ma_50": 150.0,
    "ma_200": 150.0,
    "ma_50_prev_5d": 150.0,
    "ma_200_prev_5d": 150.0,
    "current_price": 150.0,
    "high_52w": 162.0,
    "low_52w": 138.0,
    "ema_8": 150.0,
    "ema_13": 150.0,
    "ema_21": 150.0,
    "ema_34": 150.0,
    "ema_55": 150.0,
    "ribbon_compression_pct": 1.5,
    # Momentum flat
    "rsi_14": 50.0,
    "macd_line": 0.0,
    "macd_signal": 0.0,
    "macd_histogram": 0.0,
    "macd_histogram_prev": 0.0,
    "stoch_k": 50.0,
    "stoch_d": 50.0,
    "stoch_k_prev": 50.0,
    "stoch_d_prev": 50.0,
    "is_breakout": False,
    "bb_squeeze": True,
    # Sentiment flat
    "upgrades_30d": 1,
    "downgrades_30d": 1,
    "insider_purchases_count_90d": 1,
    "insider_sales_count_90d": 1,
    "news_sentiment_14d_avg": 0.0,
    # Valuation neutral / pricey-growth (peg 2.0 trips SELL)
    "pe_ratio": 22.0,
    "sector_pe_avg": 22.0,
    "forward_pe": 22.0,
    "peg_ratio": 1.2,
    "ev_ebitda": 17.0,
    # Macro neutral
    "vix_level": 18.0,
    "vix_change_5d_pct": 0.0,
    "stock_return_3m_pct": 1.0,
    "market_return_3m_pct": 1.0,
    "sector_return_3m_pct": 1.0,
    "market_regime": "sideways",
}


# ---------------------------------------------------------------------------
# Override fixtures (each merged on top of a sane baseline so the override
# is the only "loud" thing in the context).
# ---------------------------------------------------------------------------

_OVR_FRAUD: dict[str, Any] = {
    "has_fraud_allegation": True,
    "has_material_restatement": False,
    "has_sec_sebi_investigation": False,
}

_OVR_GUIDANCE_PULLED: dict[str, Any] = {
    "guidance_withdrawn_mid_year": True,
    "guidance_withdrawal_explained": False,
}

_OVR_DIVIDEND_CUT: dict[str, Any] = {
    "dividend_cut_announced": True,
    "earnings_declining": True,
}


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

# Each entry: (filename, payload). ``context`` is materialised from
# baseline + deltas at write time.

SCENARIOS: list[dict[str, Any]] = [
    # ------------------------- Strong-buy / buy -------------------------
    {
        "filename": "aapl_2023_q1_earnings_beat.json",
        "name": "Apple FY23 Q1 earnings beat",
        "description": "Strong YoY EPS, expanding margins, golden cross technicals as Apple rebounded from late-2022 weakness.",
        "source": "Real event: Apple FY23 Q1 earnings (calendar Q4 2022), reported Feb 2 2023. Stock rallied through Feb-March 2023.",
        "ticker": "AAPL", "market": "US",
        "expected_signal": "BUY", "expected_min_confidence": 65, "expected_max_confidence": 80,
        "notes": "Real events rarely score >=80. STRONG_BUY tier needs all pillars aligned (rare confluence per rules.json).",
        "deltas": [_STRONG_BULL, {
            "eps_yoy_pct": 16.5, "revenue_yoy_pct": 9.0,
            "net_margin_current": 0.247, "roe_pct": 145.0,
            "current_price": 154.5, "ma_50": 148.0, "ma_200": 150.0,
            "high_52w": 178.5, "low_52w": 124.2,
            "vix_level": 19.0,
        }],
    },
    {
        "filename": "nvda_2023_ai_breakout.json",
        "name": "Nvidia 2023 AI datacenter breakout",
        "description": "Datacenter revenue tripled YoY; gross margins expanded; stock breaking above 52-week highs on volume.",
        "source": "Real event: Nvidia Q1 FY24 earnings May 24 2023. Datacenter revenue +14% YoY guidance versus consensus +7%; stock +24% the next day.",
        "ticker": "NVDA", "market": "US",
        "expected_signal": "BUY", "expected_min_confidence": 70, "expected_max_confidence": 85,
        "notes": "Comes very close to STRONG_BUY but momentum & risk pillars need extreme alignment for >=80 (see all_pillars_aligned scenario).",
        "deltas": [_STRONG_BULL, {
            "eps_yoy_pct": 60.0, "revenue_yoy_pct": 88.0,
            "net_margin_current": 0.43, "net_margin_2q_ago": 0.27,
            "roe_pct": 35.0, "roa_pct": 22.0, "fcf_yield_pct": 7.5,
            "current_price": 380.0, "high_52w": 380.0, "low_52w": 138.0,
            "ma_50": 290.0, "ma_200": 215.0,
            "ma_50_prev_5d": 270.0, "ma_200_prev_5d": 218.0,
            "ema_8": 376.0, "ema_13": 360.0, "ema_21": 335.0,
            "ema_34": 305.0, "ema_55": 270.0,
            "is_breakout": True, "rs_line_at_3m_high": True,
            "stock_return_3m_pct": 65.0,
        }],
    },
    {
        "filename": "all_pillars_aligned_strong_buy.json",
        "name": "All eight pillars aligned (synthetic)",
        "description": "Synthetic scenario where every pillar fires strong_buy/buy tier. Pins down the rare-confluence STRONG_BUY path.",
        "source": "Composite scenario - patterned after Q1 2024 NVDA / 2017 NFLX-style 'everything is firing' moments.",
        "ticker": "PERF", "market": "US",
        "expected_signal": "STRONG_BUY", "expected_min_confidence": 80,
        "notes": "Calibrated to land just above the 80 cliff. If a rule weight changes this becomes a HOLD signal-cliff sentinel.",
        "deltas": [_STRONG_BULL, {
            # Push momentum hard - rsi_divergence_bullish is the key for MOM-001
            # strong_buy in a trending bull (rsi_14<25 is for oversold setups);
            # bounced_off_support+vol fires MOM-006 strong_buy.
            "rsi_14": 65.0, "rsi_divergence_bullish": True,
            "macd_line": 3.0, "macd_signal": 0.5,
            "macd_histogram": 2.5, "macd_histogram_prev": 1.8,
            "stoch_k": 78.0, "stoch_d": 70.0,
            "stoch_k_prev": 60.0, "stoch_d_prev": 55.0,
            "volume_avg_ratio": 2.5,
            "volume_today": 2_500_000, "volume_avg_20d": 1_000_000,
            "price_change_today_pct": 4.0,
            "is_breakout": True, "bounced_off_support_today": True,
            # Risk strong_buy: high beta in bull regime + beat-and-raise quarter
            "beta": 1.6, "vix_level": 16.0, "vix_change_5d_pct": -3.0,
            "guidance_trend": "raising",
            "is_beat_and_raise_quarter": True,
            "guidance_revisions_up_q": 2,
            "guidance_revisions_down_q": 0,
            # Macro tailwinds
            "policy_rate_trend": "cutting",
            "policy_rate_change_3m_bps": -50,
            "gdp_yoy_pct": 3.5, "cpi_yoy_pct": 2.2,
            "stock_return_3m_pct": 28.0,
            "market_return_3m_pct": 8.0,
            "sector_return_3m_pct": 22.0,
        }],
    },
    {
        "filename": "msft_2023_cloud_steady.json",
        "name": "Microsoft FY23 cloud growth",
        "description": "Steady Azure growth, strong margins, but the stock is mid-range so no euphoria.",
        "source": "Real-shape event: Microsoft FY23 Q3 earnings (Apr 2023). Azure growth ~27% YoY, decent but decelerating.",
        "ticker": "MSFT", "market": "US",
        "expected_signal": "BUY", "expected_min_confidence": 65, "expected_max_confidence": 85,
        "deltas": [_STRONG_BULL, {
            "eps_yoy_pct": 10.0, "revenue_yoy_pct": 7.0,
            "current_price": 305.0,
            "ma_50": 290.0, "ma_200": 260.0,
            "high_52w": 315.0, "low_52w": 213.0,
            "is_breakout": False, "stock_return_3m_pct": 9.0,
            "rsi_14": 58.0, "macd_histogram": 0.5,
        }],
    },
    {
        "filename": "tech_golden_cross_breakout.json",
        "name": "Pure technical golden-cross breakout",
        "description": "Synthetic mid-cap with a textbook golden cross + breakout-on-volume; fundamentals look fine.",
        "source": "Composite scenario for technical pillar regression - patterned after typical Q4 small-cap rallies.",
        "ticker": "ACME", "market": "US",
        "expected_signal": "BUY", "expected_min_confidence": 65,
        "deltas": [_STRONG_BULL, {
            "eps_yoy_pct": 12.0, "revenue_yoy_pct": 9.0,
            "fundamental_score": 65.0,
            "is_breakout": True, "bounced_off_support_today": True,
        }],
    },
    # ----------------------------- Bearish -----------------------------
    {
        "filename": "tsla_2024_delivery_miss.json",
        "name": "Tesla Q1 2024 delivery miss",
        "description": "First YoY delivery decline; price war hit margins; bearish trend with broken support.",
        "source": "Real event: Tesla Q1 2024 deliveries reported Apr 2 2024 (-8.5% YoY). Stock fell ~5% intraday and entered downtrend through April.",
        "ticker": "TSLA", "market": "US",
        "expected_signal": "SELL", "expected_min_confidence": 25, "expected_max_confidence": 45,
        "notes": "Real events rarely score <=24.99. STRONG_SELL tier needs all pillars at strong_sell or an override (see WIRECARD).",
        "deltas": [_STRONG_BEAR, {
            "current_price": 165.0, "ma_50": 195.0, "ma_200": 230.0,
            "high_52w": 299.0, "low_52w": 160.0,
            "eps_yoy_pct": -55.0, "revenue_yoy_pct": -9.0,
        }],
    },
    {
        "filename": "peloton_2022_post_pandemic_collapse.json",
        "name": "Peloton 2022 post-pandemic unwind",
        "description": "Demand collapse, recurring losses, ballooning debt - a 'systemic breakdown' classic.",
        "source": "Real event: Peloton FY22 Q3 earnings (May 10 2022). Revenue -23% YoY, $1B-ish FCF burn run-rate, dilutive raises.",
        "ticker": "PTON", "market": "US",
        "expected_signal": "SELL", "expected_min_confidence": 25, "expected_max_confidence": 45,
        "notes": "Real events rarely score <=24.99. STRONG_SELL tier comes from override paths (see WIRECARD).",
        "deltas": [_STRONG_BEAR, {
            "sector": "consumer_cyclical",
            "stock_sector": "consumer_cyclical",
            "stock_sector_classification": "cyclical",
            "current_price": 12.0, "ma_50": 21.0, "ma_200": 50.0,
            "high_52w": 90.0, "low_52w": 11.0,
            "fcf_negative_quarters_consecutive": 6,
            "debt_to_equity": 4.5, "interest_coverage_ratio": 0.4,
        }],
    },
    {
        "filename": "meta_2022_ad_slowdown.json",
        "name": "Meta 2022 ad-slowdown reset",
        "description": "First-ever revenue decline + heavy capex on Reality Labs - sentiment deeply negative but balance sheet still strong.",
        "source": "Real event: Meta Q3 2022 earnings (Oct 26 2022). Stock fell 24% next day. Revenue -4% YoY; opex up 19%.",
        "ticker": "META", "market": "US",
        "expected_signal": "SELL", "expected_min_confidence": 20, "expected_max_confidence": 45,
        "deltas": [_STRONG_BEAR, {
            "debt_to_equity": 0.3, "current_ratio": 2.7, "quick_ratio": 2.5,
            "interest_coverage_ratio": 35.0,
            "fcf_negative_quarters_consecutive": 0, "fcf_yield_pct": 4.0,
            "current_price": 95.0, "ma_50": 130.0, "ma_200": 175.0,
            "high_52w": 384.0, "low_52w": 88.0,
            "eps_yoy_pct": -50.0, "revenue_yoy_pct": -4.0,
            "vix_level": 28.0,
        }],
    },
    {
        "filename": "bear_flag_breakdown.json",
        "name": "Synthetic bear-flag breakdown",
        "description": "Death cross + momentum collapse on heavy distribution volume - pure technical bearish setup.",
        "source": "Composite scenario for technical pillar regression. Pattern lifted from common 2022 high-multiple breakdowns.",
        "ticker": "BEARCO", "market": "US",
        "expected_signal": "SELL",
        "deltas": [_STRONG_BEAR, {
            "eps_yoy_pct": 0.0, "revenue_yoy_pct": 1.0,
            "earnings_declining": False,
            "fundamental_score": 50.0,
            "interest_coverage_ratio": 6.0,
            "debt_to_equity": 1.0,
            "vix_level": 22.0, "vix_change_5d_pct": 8.0,
        }],
    },
    # ----------------------------- Overrides ---------------------------
    {
        "filename": "wirecard_fraud_signals.json",
        "name": "Wirecard pre-collapse fraud signals",
        "description": "Cash-balance restatement + auditor flags + open SEC/SEBI-equivalent (BaFin) probe - any one fires OVR-O1.",
        "source": "Real event: Wirecard Jun 2020. Auditor refused to sign FY19 accounts; 1.9bn EUR cash 'missing'. Stock fell 99% in three days.",
        "ticker": "WDI.DE", "market": "US",
        "expected_signal": "STRONG_SELL", "expected_overrides": ["OVR-O1"],
        "deltas": [_STRONG_BEAR, _OVR_FRAUD, {
            "has_fraud_allegation": True, "has_material_restatement": True,
            "has_sec_sebi_investigation": True,
            "current_price": 30.0, "ma_50": 110.0, "ma_200": 130.0,
            "high_52w": 145.0, "low_52w": 28.0,
        }],
    },
    {
        "filename": "guidance_withdrawn_panic.json",
        "name": "Mid-year guidance withdrawal w/ no explanation",
        "description": "Healthy-looking financials but management pulls full-year guidance with no rationale - OVR-O2 trips.",
        "source": "Composite scenario - patterned after the COVID-era March 2020 'pulling guidance' wave.",
        "ticker": "OPAQ", "market": "US",
        "expected_signal": "SELL", "expected_overrides": ["OVR-O2"],
        "deltas": [_OVR_GUIDANCE_PULLED, {
            "current_price": 80.0,
            "ma_50": 80.0, "ma_200": 78.0,
            "high_52w": 92.0, "low_52w": 72.0,
        }],
    },
    {
        "filename": "ge_2018_dividend_cut.json",
        "name": "GE 2018 dividend cut on falling earnings",
        "description": "Income-portfolio override OVR-O3: cut + earnings_declining together = forced SELL.",
        "source": "Real event: GE cut its dividend by 50% on Nov 13 2017 and again to 1c in Oct 2018 amid worsening industrial earnings.",
        "ticker": "GE", "market": "US",
        "expected_signal": "SELL", "expected_overrides": ["OVR-O3"],
        "deltas": [_OVR_DIVIDEND_CUT, {
            "sector": "industrials",
            "stock_sector": "industrials",
            "stock_sector_classification": "cyclical",
            "current_price": 9.0, "ma_50": 12.0, "ma_200": 15.0,
            "high_52w": 19.0, "low_52w": 8.5,
            "eps_yoy_pct": -25.0, "revenue_yoy_pct": -3.0,
            "earnings_declining": True,
            "dividend_yield_pct": 4.5, "payout_ratio_pct": 80.0,
            "fundamental_score": 38.0,
            "interest_coverage_ratio": 3.0,
        }],
    },
    # ------------------------------ Hold ------------------------------
    {
        "filename": "kogi_defensive_steady.json",
        "name": "Defensive blue-chip steady state",
        "description": "Mature defensive name (think KO) - flat growth, fair valuation, no catalyst. Expected HOLD.",
        "source": "Composite scenario - patterned after Coca-Cola in mid-2023 quiet periods.",
        "ticker": "KO", "market": "US",
        "expected_signal": "HOLD",
        "deltas": [_MIXED_NEUTRAL, {
            "sector": "consumer_defensive",
            "stock_sector": "consumer_defensive",
            "stock_sector_classification": "defensive",
            "is_growth_stock": False,
            "dividend_yield_pct": 3.1, "payout_ratio_pct": 75.0,
            "current_price": 60.0,
            "high_52w": 65.0, "low_52w": 55.0,
            "ma_50": 60.0, "ma_200": 60.0,
            "eps_yoy_pct": 4.0, "revenue_yoy_pct": 3.0,
            "roe_pct": 38.0, "fcf_yield_pct": 3.5,
            "interest_coverage_ratio": 14.0,
            "debt_to_equity": 1.6,
        }],
    },
    {
        "filename": "mixed_signals_offsetting.json",
        "name": "Mixed signals - bull tech vs bear fundamentals",
        "description": "Strong technicals on a stock with weakening fundamentals - signals cancel; expected HOLD.",
        "source": "Composite scenario - patterned after late-cycle momentum names that rally on flows despite earnings cracks.",
        "ticker": "MIXD", "market": "US",
        "expected_signal": "HOLD",
        "deltas": [{
            "current_price": 200.0,
            "ma_50": 195.0, "ma_200": 175.0, "ma_50_prev_5d": 180.0,
            "high_52w": 205.0, "low_52w": 130.0,
            "rsi_14": 65.0, "macd_line": 1.2, "macd_signal": 0.3,
            "is_breakout": True, "ema_8": 202.0, "ema_13": 198.0,
            "ema_21": 192.0, "ema_34": 184.0, "ema_55": 175.0,
            "ribbon_compression_pct": 9.0,
            "eps_yoy_pct": -8.0, "revenue_yoy_pct": -2.0,
            "net_margin_current": 0.10, "net_margin_2q_ago": 0.13,
            "earnings_declining": True, "margin_improving": False,
            "fcf_yield_pct": 1.0, "fundamental_score": 45.0,
            "debt_to_equity": 1.4, "interest_coverage_ratio": 4.5,
            "stock_return_3m_pct": 18.0, "market_return_3m_pct": 5.0,
        }],
    },
    # ---------------------------- Edge cases ---------------------------
    {
        "filename": "partial_data_technical_only.json",
        "name": "Partial data - only technicals available (pre-2015 GDELT gap)",
        "description": "Tests graceful degradation: only price-derived fields populated (no fundamentals, no sentiment, no macro detail).",
        "source": "Synthetic - simulates the data shape we get for backtests pre-2015 when GDELT/news + analyst-rec data is missing.",
        "ticker": "OLD", "market": "US",
        "expected_signal": "HOLD",
        "expected_min_confidence": 35,
        "expected_max_confidence": 70,
        "context_full": True,  # don't merge baseline; supply minimal ctx directly
        "deltas": [{
            "market": "US",
            "current_price": 100.0,
            "ma_50": 95.0, "ma_200": 92.0,
            "ma_50_prev_5d": 93.0, "ma_200_prev_5d": 92.0,
            "high_52w": 110.0, "low_52w": 80.0,
            "ema_8": 100.5, "ema_13": 99.0, "ema_21": 97.0,
            "ema_34": 94.0, "ema_55": 92.0,
            "ribbon_compression_pct": 8.5,
            "rsi_14": 55.0,
            "macd_line": 0.4, "macd_signal": 0.3, "macd_histogram": 0.1,
            "stoch_k": 55.0, "stoch_d": 53.0,
            "bb_upper": 105.0, "bb_middle": 98.0, "bb_lower": 91.0,
            "volume_today": 1_000_000, "volume_avg_20d": 1_000_000,
            "volume_avg_ratio": 1.0, "is_breakout": False,
            "nearest_support": 94.0, "nearest_resistance": 106.0,
            "broke_support_today": False, "bounced_off_support_today": False,
            "market_regime": "sideways",
        }],
    },
    {
        "filename": "macro_recession_cyclical_pressure.json",
        "name": "Recession macro on a cyclical name",
        "description": "Macro headwind + cyclical sector + lagging RS produces a SELL, even with merely-OK fundamentals.",
        "source": "Composite scenario - patterned after Q4 2022 industrial cyclicals during the rate-hike scare.",
        "ticker": "CYCL", "market": "US",
        "expected_signal": "SELL",
        "deltas": [{
            "sector": "industrials",
            "stock_sector": "industrials",
            "stock_sector_classification": "cyclical",
            "is_growth_stock": False,
            "current_price": 70.0,
            "ma_50": 78.0, "ma_200": 85.0,
            "ma_50_prev_5d": 84.0, "ma_200_prev_5d": 85.0,
            "high_52w": 102.0, "low_52w": 65.0,
            "ema_8": 71.0, "ema_13": 73.0, "ema_21": 76.0,
            "ema_34": 80.0, "ema_55": 84.0,
            "ribbon_compression_pct": 18.0,
            "eps_yoy_pct": -8.0, "revenue_yoy_pct": -3.0,
            "net_margin_current": 0.08, "net_margin_2q_ago": 0.09,
            "earnings_declining": True, "margin_improving": False,
            "fcf_yield_pct": 1.5, "fundamental_score": 40.0,
            "debt_to_equity": 1.4, "interest_coverage_ratio": 3.0,
            "rsi_14": 35.0, "macd_line": -0.6, "macd_signal": -0.2,
            "macd_histogram": -0.4, "macd_histogram_prev": -0.2,
            "stoch_k": 30.0, "stoch_d": 35.0,
            "is_breakout": False, "broke_support_today": False,
            "policy_rate_trend": "rising",
            "gdp_yoy_pct": -0.5, "cpi_yoy_pct": 5.5,
            "market_regime": "bear",
            "stock_return_3m_pct": -18.0, "market_return_3m_pct": -2.0,
            "sector_return_3m_pct": -10.0, "rs_line_at_3m_high": False,
            "vix_level": 28.0, "vix_change_5d_pct": 12.0, "beta": 1.4,
            "guidance_trend": "lowering",
            "upgrades_30d": 0, "downgrades_30d": 3,
            "insider_purchases_count_90d": 0, "insider_sales_count_90d": 5,
            "exec_holdings_pct_sold_90d": 25.0,
            "news_sentiment_14d_avg": -0.32,
            "negative_news_volume_spike": True,
            "institutional_exits_qoq": 3,
            "institutional_ownership_change_pct": -3.0,
        }],
    },
]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _payload_for(scenario: dict[str, Any]) -> dict[str, Any]:
    if scenario.get("context_full"):
        # Full override - context is only what's in deltas (no baseline).
        ctx = {}
        for d in scenario["deltas"]:
            ctx.update(d)
    else:
        ctx = _merge(*scenario["deltas"])

    payload: dict[str, Any] = {
        "name": scenario["name"],
        "description": scenario["description"],
        "source": scenario["source"],
        "ticker": scenario["ticker"],
        "market": scenario["market"],
        "expected_signal": scenario["expected_signal"],
    }
    if "expected_overrides" in scenario:
        payload["expected_overrides"] = scenario["expected_overrides"]
    if "expected_min_confidence" in scenario:
        payload["expected_min_confidence"] = scenario["expected_min_confidence"]
    if "expected_max_confidence" in scenario:
        payload["expected_max_confidence"] = scenario["expected_max_confidence"]
    payload["context"] = ctx
    return payload


def write_all(out_dir: Path | None = None) -> list[Path]:
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for scenario in SCENARIOS:
        payload = _payload_for(scenario)
        path = out_dir / scenario["filename"]
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


if __name__ == "__main__":
    written = write_all()
    print(f"Wrote {len(written)} scenarios:")
    for p in written:
        print(f"  - {p.name}")

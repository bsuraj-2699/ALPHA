"""
Test harness for RuleEvaluator.

Runs 6 realistic scenarios spanning the signal spectrum:
  1. AAPL    - Strong Buy: high quality megacap with momentum
  2. RELIANCE.NS - Buy: solid Indian large-cap, mixed signals
  3. TCS.NS   - Hold: defensive, fully-priced
  4. META    - Mixed: high P/E but strong fundamentals (tests valuation/growth tension)
  5. WEAK    - Strong Sell: synthetic ailing company
  6. FRAUD   - Override test: should force STRONG_SELL regardless of score
"""

from pathlib import Path

from rule_evaluator import RuleEvaluator

RULES_PATH = Path(__file__).parent / "rules.json"


# Helper to merge scenario dicts compactly
def merge(*dicts):
    out = {}
    for d in dicts:
        out.update(d)
    return out


# ----------------------------------------------------------------------------
# Building blocks (typical good / bad / neutral signals across each pillar)
# ----------------------------------------------------------------------------

GOOD_FUNDAMENTALS = {
    "eps_yoy_pct": 22, "eps_qoq_pct": 5, "eps_misses_consecutive": 0,
    "revenue_yoy_pct": 14, "revenue_decline_quarters_consecutive": 0,
    "net_margin_current": 26, "net_margin_2q_ago": 24, "industry_avg_margin": 18,
    "roe_pct": 28, "roa_pct": 14, "debt_to_equity_change_yoy": -0.05,
    "fcf_yield_pct": 6.5, "fcf_negative_quarters_consecutive": 0, "company_age_years": 30,
}

GOOD_BALANCE_SHEET = {
    "debt_to_equity": 0.4, "debt_to_equity_yoy_change": -0.05, "sector": "default",
    "current_ratio": 1.9, "quick_ratio": 1.6,
    "interest_coverage_ratio": 12,
}

GOOD_TREND = {
    "ma_50": 195, "ma_200": 175, "ma_50_prev_5d": 192, "ma_200_prev_5d": 175,
    "current_price": 198, "high_52w": 200, "low_52w": 140, "fundamental_score": 72,
    "ema_8": 197, "ema_13": 195, "ema_21": 192, "ema_34": 188, "ema_55": 185,
    "ribbon_compression_pct": 6.0,
}

GOOD_MOMENTUM = {
    "rsi_14": 58, "rsi_divergence_bearish": False, "rsi_divergence_bullish": False,
    "macd_line": 1.2, "macd_signal": 0.9, "macd_histogram": 0.3, "macd_histogram_prev": 0.2,
    "stoch_k": 60, "stoch_d": 55, "stoch_k_prev": 58, "stoch_d_prev": 56,
    "volume_today": 1_800_000, "volume_avg_20d": 1_000_000,
    "price_change_today_pct": 1.4, "is_breakout": False,
    "bb_upper": 205, "bb_middle": 195, "bb_lower": 185, "bb_squeeze": False,
    "nearest_support": 188, "nearest_resistance": 205,
    "broke_support_today": False, "bounced_off_support_today": False,
}

GOOD_SENTIMENT = {
    "upgrades_30d": 4, "downgrades_30d": 0,
    "target_price_avg": 240, # current_price=198 → ~21% upside
    "insider_purchases_count_90d": 3, "insider_sales_count_90d": 0,
    "exec_holdings_pct_sold_90d": 0,
    "short_interest_pct_float": 1.5, "days_to_cover": 1.2,
    "short_interest_change_30d": -1, "has_positive_catalyst": True,
    "new_institutional_positions_qoq": 4, "institutional_exits_qoq": 1,
    "institutional_ownership_change_pct": 3.5,
    "news_sentiment_14d_avg": 0.45, "negative_news_volume_spike": False,
}

GOOD_MACRO = {
    "policy_rate_trend": "cutting", "policy_rate_change_3m_bps": -50,
    "stock_sector": "technology",
    "favorable_sectors_for_cuts": ["technology", "growth", "real_estate", "utilities"],
    "unfavorable_sectors_for_hikes": ["technology", "growth", "real_estate", "utilities"],
    "gdp_yoy_pct": 3.2, "gdp_yoy_pct_prev_quarter": 3.0,
    "stock_sector_classification": "cyclical",
    "cpi_yoy_pct": 2.8,
    "stock_return_3m_pct": 14, "sector_return_3m_pct": 8, "market_return_3m_pct": 5,
    "rs_line_at_3m_high": True,
    "dxy_change_3m_pct_US": -2, "inr_change_3m_pct_IN": 0,
    "foreign_revenue_pct": 35, "geopolitical_exposure_score": 0.15,
}

GOOD_VALUATION_GROWTH = {
    "pe_ratio": 28, "sector_pe_avg": 32, "pe_5y_avg": 26,
    "is_growth_stock": True, "forward_pe": 25, "revenue_growing": True,
    "peg_ratio": 1.1,
    "ev_ebitda": 18, "industry_ev_ebitda_median": 22, "margin_improving": True,
    "pb_ratio": 8, "is_financial_sector": False,
    "dividend_yield_pct": 0.5, "payout_ratio_pct": 15,
    "earnings_declining": False, "dividend_growth_5y_pct": 6,
}

GOOD_RISK = {
    "beta": 1.15, "market_regime": "bull",
    "guidance_revisions_up_q": 1, "guidance_revisions_down_q": 0,
    "is_beat_and_raise_quarter": True,
    "vix_level": 18, "vix_change_5d_pct": 5,
    # for VIX rule that references fundamental_score
}

# Override-related (none triggered)
NO_OVERRIDES = {
    "has_fraud_allegation": False, "has_material_restatement": False,
    "has_sec_sebi_investigation": False,
    "guidance_withdrawn_mid_year": False, "guidance_withdrawal_explained": True,
    "dividend_cut_announced": False,
    "price_vs_avg_purchase_price_pct": 2,
    "position_pct_of_portfolio": 4,
}


# ----------------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------------

SCENARIOS = []

# 1. AAPL — solid megacap, expected STRONG_BUY or BUY
SCENARIOS.append(("AAPL", "US", merge(
    GOOD_FUNDAMENTALS, GOOD_BALANCE_SHEET, GOOD_TREND, GOOD_MOMENTUM,
    GOOD_SENTIMENT, GOOD_MACRO, GOOD_VALUATION_GROWTH, GOOD_RISK, NO_OVERRIDES,
)))

# 2. RELIANCE.NS — Indian large-cap, mostly good but moderate growth
reliance_overrides = {
    "eps_yoy_pct": 8,            # below 10% threshold
    "revenue_yoy_pct": 7,        # also below 8%
    "fcf_yield_pct": 4.2,        # below 5%
    "pe_ratio": 26, "sector_pe_avg": 24, "is_growth_stock": False,
    "stock_sector": "energy", "stock_sector_classification": "cyclical",
    "policy_rate_trend": "neutral", "policy_rate_change_3m_bps": 0,
    "upgrades_30d": 2, "downgrades_30d": 1,
    "insider_purchases_count_90d": 0, "insider_sales_count_90d": 1,
    "exec_holdings_pct_sold_90d": 5,
    "rs_line_at_3m_high": False,
    "stock_return_3m_pct": 6, "sector_return_3m_pct": 5, "market_return_3m_pct": 5,
}
SCENARIOS.append(("RELIANCE.NS", "IN", merge(
    GOOD_FUNDAMENTALS, GOOD_BALANCE_SHEET, GOOD_TREND, GOOD_MOMENTUM,
    GOOD_SENTIMENT, GOOD_MACRO, GOOD_VALUATION_GROWTH, GOOD_RISK, NO_OVERRIDES,
    reliance_overrides,
)))

# 3. TCS.NS — defensive IT, fully priced, mid-band
tcs_overrides = {
    "eps_yoy_pct": 6, "revenue_yoy_pct": 5,
    "pe_ratio": 30, "sector_pe_avg": 28,
    "ma_50": 3700, "ma_200": 3650, "current_price": 3680,
    "high_52w": 4200, "low_52w": 3500,
    "rsi_14": 50, "macd_line": 0.1, "macd_signal": 0.05,
    "stoch_k": 50, "stoch_d": 48,
    "ema_8": 3680, "ema_13": 3675, "ema_21": 3672, "ema_34": 3668, "ema_55": 3665,
    "ribbon_compression_pct": 0.8,  # tight
    "bb_upper": 3850, "bb_lower": 3550, "bb_middle": 3700,
    "nearest_support": 3600, "nearest_resistance": 3800,
    "stock_return_3m_pct": 2, "sector_return_3m_pct": 3, "market_return_3m_pct": 5,
    "rs_line_at_3m_high": False,
    "upgrades_30d": 1, "downgrades_30d": 1,
    "insider_purchases_count_90d": 0, "insider_sales_count_90d": 0,
    "guidance_revisions_up_q": 0, "guidance_revisions_down_q": 0,
    "is_beat_and_raise_quarter": False,
    "stock_sector": "technology",
    "stock_sector_classification": "cyclical",
}
SCENARIOS.append(("TCS.NS", "IN", merge(
    GOOD_FUNDAMENTALS, GOOD_BALANCE_SHEET, GOOD_TREND, GOOD_MOMENTUM,
    GOOD_SENTIMENT, GOOD_MACRO, GOOD_VALUATION_GROWTH, GOOD_RISK, NO_OVERRIDES,
    tcs_overrides,
)))

# 4. META — high P/E growth name, tests valuation rule sensitivity
meta_overrides = {
    "pe_ratio": 35, "sector_pe_avg": 28, "is_growth_stock": True,
    "forward_pe": 30, "revenue_growing": True,
    "peg_ratio": 1.4,  # neutral
    "ev_ebitda": 20, "industry_ev_ebitda_median": 18,
    "pb_ratio": 7,
    "stock_sector": "technology",
}
SCENARIOS.append(("META", "US", merge(
    GOOD_FUNDAMENTALS, GOOD_BALANCE_SHEET, GOOD_TREND, GOOD_MOMENTUM,
    GOOD_SENTIMENT, GOOD_MACRO, GOOD_VALUATION_GROWTH, GOOD_RISK, NO_OVERRIDES,
    meta_overrides,
)))

# 5. WEAK — synthetic ailing company, expected STRONG_SELL
WEAK_FUNDAMENTALS = {
    "eps_yoy_pct": -28, "eps_qoq_pct": -10, "eps_misses_consecutive": 3,
    "revenue_yoy_pct": -18, "revenue_decline_quarters_consecutive": 4,
    "net_margin_current": 2, "net_margin_2q_ago": 9, "industry_avg_margin": 12,
    "roe_pct": 3, "roa_pct": 0.5, "debt_to_equity_change_yoy": 0.3,
    "fcf_yield_pct": -3, "fcf_negative_quarters_consecutive": 5, "company_age_years": 40,
}
WEAK_BALANCE_SHEET = {
    "debt_to_equity": 4.5, "debt_to_equity_yoy_change": 0.6, "sector": "default",
    "current_ratio": 0.85, "quick_ratio": 0.6,
    "interest_coverage_ratio": 0.9,
}
WEAK_TREND = {
    "ma_50": 80, "ma_200": 110, "ma_50_prev_5d": 85, "ma_200_prev_5d": 110,
    "current_price": 75, "high_52w": 150, "low_52w": 70, "fundamental_score": 25,
    "ema_8": 75, "ema_13": 78, "ema_21": 82, "ema_34": 90, "ema_55": 100,
    "ribbon_compression_pct": 8,
}
WEAK_MOMENTUM = {
    "rsi_14": 28, "rsi_divergence_bearish": True, "rsi_divergence_bullish": False,
    "macd_line": -1.5, "macd_signal": -0.8, "macd_histogram": -0.7, "macd_histogram_prev": -0.5,
    "stoch_k": 18, "stoch_d": 22, "stoch_k_prev": 25, "stoch_d_prev": 28,
    "volume_today": 5_000_000, "volume_avg_20d": 2_000_000,
    "price_change_today_pct": -3.5, "is_breakout": False,
    "bb_upper": 95, "bb_middle": 82, "bb_lower": 72, "bb_squeeze": False,
    "nearest_support": 72, "nearest_resistance": 95,
    "broke_support_today": True, "bounced_off_support_today": False,
}
WEAK_SENTIMENT = {
    "upgrades_30d": 0, "downgrades_30d": 4,
    "target_price_avg": 70, "insider_purchases_count_90d": 0,
    "insider_sales_count_90d": 6, "exec_holdings_pct_sold_90d": 45,
    "short_interest_pct_float": 28, "days_to_cover": 12,
    "short_interest_change_30d": 12, "has_positive_catalyst": False,
    "new_institutional_positions_qoq": 0, "institutional_exits_qoq": 5,
    "institutional_ownership_change_pct": -7,
    "news_sentiment_14d_avg": -0.55, "negative_news_volume_spike": True,
}
WEAK_MACRO = {
    "policy_rate_trend": "hiking", "policy_rate_change_3m_bps": 100,
    "stock_sector": "technology",
    "favorable_sectors_for_cuts": ["technology", "growth", "real_estate", "utilities"],
    "unfavorable_sectors_for_hikes": ["technology", "growth", "real_estate", "utilities"],
    "gdp_yoy_pct": -0.5, "gdp_yoy_pct_prev_quarter": 0.2,
    "stock_sector_classification": "cyclical",
    "cpi_yoy_pct": 7,
    "stock_return_3m_pct": -25, "sector_return_3m_pct": -8, "market_return_3m_pct": -2,
    "rs_line_at_3m_high": False,
    "dxy_change_3m_pct_US": 8, "inr_change_3m_pct_IN": 2,
    "foreign_revenue_pct": 50, "geopolitical_exposure_score": 0.6,
}
WEAK_VALUATION = {
    "pe_ratio": 65, "sector_pe_avg": 25, "pe_5y_avg": 30,
    "is_growth_stock": False, "forward_pe": 70, "revenue_growing": False,
    "peg_ratio": 2.5, "ev_ebitda": 35, "industry_ev_ebitda_median": 18,
    "margin_improving": False, "pb_ratio": 12, "is_financial_sector": False,
    "dividend_yield_pct": 6, "payout_ratio_pct": 110,
    "earnings_declining": True, "dividend_growth_5y_pct": -2,
}
WEAK_RISK = {
    "beta": 1.8, "market_regime": "bear",
    "guidance_revisions_up_q": 0, "guidance_revisions_down_q": 3,
    "is_beat_and_raise_quarter": False,
    "vix_level": 14, "vix_change_5d_pct": -8,
}
SCENARIOS.append(("WEAK", "US", merge(
    WEAK_FUNDAMENTALS, WEAK_BALANCE_SHEET, WEAK_TREND, WEAK_MOMENTUM,
    WEAK_SENTIMENT, WEAK_MACRO, WEAK_VALUATION, WEAK_RISK, NO_OVERRIDES,
)))

# 6. FRAUD — override test, otherwise looks fine
fraud_overrides = {
    "has_fraud_allegation": True,  # SHOULD force STRONG_SELL
    "has_material_restatement": False,
    "has_sec_sebi_investigation": False,
    "guidance_withdrawn_mid_year": False, "guidance_withdrawal_explained": True,
    "dividend_cut_announced": False,
    "price_vs_avg_purchase_price_pct": 5,
    "position_pct_of_portfolio": 3,
}
SCENARIOS.append(("FRAUDCO", "US", merge(
    GOOD_FUNDAMENTALS, GOOD_BALANCE_SHEET, GOOD_TREND, GOOD_MOMENTUM,
    GOOD_SENTIMENT, GOOD_MACRO, GOOD_VALUATION_GROWTH, GOOD_RISK,
    fraud_overrides,
)))


# ----------------------------------------------------------------------------
# Run
# ----------------------------------------------------------------------------

def main():
    evaluator = RuleEvaluator(RULES_PATH)
    results = []
    for ticker, market, ctx in SCENARIOS:
        result = evaluator.evaluate(ticker, market, ctx)
        results.append(result)
        print(result.summary())
        print()

    # Brief per-rule diagnostics for AAPL only (full audit trail demo)
    print("=" * 60)
    print("FULL RULE BREAKDOWN — AAPL")
    print("=" * 60)
    aapl = results[0]
    for pillar in aapl.pillar_details:
        print(f"\n{pillar.pillar.upper()} (score: {pillar.score:.1f})")
        for r in pillar.rule_results:
            tag = "⏭️ " if r.tier == "skipped" else "  "
            print(f"  {tag}[{r.rule_id}] {r.rule_name:50s} {r.tier:12s} score={r.score:5.1f}")


if __name__ == "__main__":
    main()

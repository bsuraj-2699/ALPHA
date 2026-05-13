"""Coverage test: assert ContextBuilder populates ≥90% of fields the
RuleEvaluator's `data_required` lists ask for, by market.

Failing this test means a rule asks for data no provider supplies — fix the
data layer or remove the field from the rule.

The tolerated absent set captures fields that genuinely require paid feeds or
that aren't available for a given market. They do NOT count against coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Fields we consider "out of Phase-3 scope" — paid data, market-specific, or
# bespoke (geopolitical scoring). These are excluded from the coverage target
# so the test fails only when a *fixable* gap appears.
TOLERATED_ABSENT: dict[str, set[str]] = {
    "US": {
        "industry_avg_margin",       # paid: peer aggregation
        "sector_pe_avg",             # paid: peer aggregation
        "pe_5y_avg",                 # paid: long-history aggregate
        "industry_ev_ebitda_median", # paid: peer aggregation
        "geopolitical_exposure_score",  # bespoke / no public source
        "foreign_revenue_pct",       # paid: geographic segment data
        # Override-only inputs (not on the build path, populated by user/UI):
        "has_fraud_allegation",
        "has_material_restatement",
        "has_sec_sebi_investigation",
        "guidance_withdrawn_mid_year",
        "guidance_withdrawal_explained",
        "dividend_cut_announced",
        "price_vs_avg_purchase_price_pct",
        "position_pct_of_portfolio",
    },
    "IN": {
        "industry_avg_margin",
        "sector_pe_avg",
        "pe_5y_avg",
        "industry_ev_ebitda_median",
        "geopolitical_exposure_score",
        "foreign_revenue_pct",
        "short_interest_pct_float",  # SENT-003 marks IN out-of-scope itself
        "days_to_cover",
        "short_interest_change_30d",
        "has_positive_catalyst",     # tied to short_interest
        "has_fraud_allegation",
        "has_material_restatement",
        "has_sec_sebi_investigation",
        "guidance_withdrawn_mid_year",
        "guidance_withdrawal_explained",
        "dividend_cut_announced",
        "price_vs_avg_purchase_price_pct",
        "position_pct_of_portfolio",
    },
}

COVERAGE_TARGET = 0.90


def _all_required_fields() -> set[str]:
    rules_path = Path(__file__).resolve().parents[2] / "core" / "rules.json"
    spec = json.loads(rules_path.read_text())
    fields: set[str] = set()
    for rule in spec["rules"]:
        for f in rule.get("data_required", []):
            fields.add(f)
    return fields


@pytest.fixture(scope="module")
def required_fields() -> set[str]:
    return _all_required_fields()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("ticker,market", [("AAPL", "US"), ("RELIANCE.NS", "IN")])
async def test_context_field_coverage(ticker: str, market: str, required_fields: set[str]) -> None:
    pytest.importorskip("yfinance")
    pytest.importorskip("pandas")
    from packages.data.context_builder import ContextBuilder, _build_default_providers

    providers, screener, nse, gdelt = _build_default_providers(market)
    builder = ContextBuilder(providers, screener=screener, nse=nse, gdelt=gdelt)
    ctx = await builder.build(ticker, market)

    market_specific = {f for f in required_fields if f.endswith("_US") or f.endswith("_IN")}
    expected_fields = (required_fields - market_specific) - TOLERATED_ABSENT[market]
    # Add back the market-specific field that DOES apply to this market.
    for f in market_specific:
        if f.endswith(f"_{market}"):
            expected_fields.add(f)

    populated = {f for f in expected_fields if f in ctx}
    coverage = len(populated) / len(expected_fields) if expected_fields else 1.0
    missing = sorted(expected_fields - populated)
    assert coverage >= COVERAGE_TARGET, (
        f"{ticker}/{market}: coverage {coverage:.0%} < {COVERAGE_TARGET:.0%}.\n"
        f"Missing ({len(missing)}/{len(expected_fields)}): {missing}"
    )

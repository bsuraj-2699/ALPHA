"""ContextBuilder fundamentals precedence: Upstox > Screener > Yahoo (offline)."""

from __future__ import annotations

from packages.data.context_builder import ContextBuilder


class _FakeUpstox:
    name = "upstox"
    supported_markets = ("IN",)

    async def get_fundamentals(self, ticker, market):
        raise NotImplementedError

    async def fundamentals_context(self, ticker, market):
        return {"pe_ratio": 20.0, "roe_pct": 15.0}


class _FakeScreener:
    async def get_fundamentals(self, ticker):
        # Screener resolves pe (loses to Upstox) and debt_to_equity (unique).
        return {"pe_ratio": 99.0, "roe_pct": 88.0, "debt_to_equity": 0.5}


async def test_upstox_wins_screener_fills_gaps():
    builder = ContextBuilder([_FakeUpstox()], screener=_FakeScreener())
    out = await builder._fundamentals_block("TESTCO", "IN")

    assert out["pe_ratio"] == 20.0      # Upstox overrides Screener
    assert out["roe_pct"] == 15.0       # Upstox overrides Screener
    assert out["debt_to_equity"] == 0.5  # Screener-only key survives
    assert out["beta"] == 1.0           # default safety net preserved


async def test_screener_used_when_upstox_empty():
    class _EmptyUpstox(_FakeUpstox):
        async def fundamentals_context(self, ticker, market):
            return {}

    builder = ContextBuilder([_EmptyUpstox()], screener=_FakeScreener())
    out = await builder._fundamentals_block("TESTCO", "IN")
    assert out["pe_ratio"] == 99.0  # falls back to Screener
    assert out["debt_to_equity"] == 0.5

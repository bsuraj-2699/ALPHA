"""UpstoxProvider fundamentals mapping + instrument resolution (offline)."""

from __future__ import annotations

import gzip
import json
from datetime import date

from packages.data.providers.upstox import _V3_BASE, UpstoxProvider
from packages.data.providers.upstox_instruments import InstrumentMaster

_ROWS = [
    {
        "segment": "NSE_EQ",
        "isin": "INE081A01020",
        "trading_symbol": "TESTCO",
        "instrument_key": "NSE_EQ|INE081A01020",
        "name": "Test Co",
    }
]


class _FakeCache:
    async def get(self, key):
        return None

    async def set(self, key, value, ttl=None):
        return None


def _master() -> InstrumentMaster:
    async def _fetch(url: str) -> bytes:
        rows = _ROWS if "NSE" in url else []
        return gzip.compress(json.dumps(rows).encode())

    return InstrumentMaster(cache=None, fetcher=_fetch)


def _provider() -> UpstoxProvider:
    return UpstoxProvider(
        api_key="k", api_secret="s", access_token="t",
        cache=_FakeCache(), instrument_master=_master(),
    )


_KEY_RATIOS = {
    "status": "success",
    "data": [
        {"name": "P/E", "company_value": "20.15", "sector_value": "12.46"},
        {"name": "P/B", "company_value": "2.13"},
        {"name": "ROE", "company_value": "8.94%"},
        {"name": "ROA", "company_value": "4.39%"},
        {"name": "EV/EBITDA", "company_value": "10.25"},
    ],
}
_INCOME = {
    "status": "success",
    "data": {
        "units_in": "crore",
        "income_statement": [
            {"category": "Revenue", "history": [
                {"value": "1000", "period": "Mar 2025"},
                {"value": "800", "period": "Mar 2024"},
            ]},
            {"category": "Net Profit", "history": [
                {"value": "150", "period": "Mar 2025"},
                {"value": "120", "period": "Mar 2024"},
            ]},
        ],
        "full_statement": [
            {"particular": "EPS - Basic", "history": [
                {"value": "52", "period": "Mar 2025"},
                {"value": "40", "period": "Mar 2024"},
            ]},
        ],
    },
}


async def test_fundamentals_context_maps_all_metrics(monkeypatch):
    p = _provider()

    async def fake_request(path, params=None, limiter=None, base=None):
        if "key-ratios" in path:
            return _KEY_RATIOS
        if "income-statement" in path:
            return _INCOME
        return None

    monkeypatch.setattr(p, "_request", fake_request)
    out = await p.fundamentals_context("TESTCO", "IN")

    assert out["pe_ratio"] == 20.15
    assert out["pb_ratio"] == 2.13
    assert out["roe_pct"] == 8.94
    assert out["roa_pct"] == 4.39
    assert out["ev_ebitda"] == 10.25
    assert out["revenue_yoy_pct"] == 25.0
    assert out["net_margin_current"] == 15.0
    assert out["eps_yoy_pct"] == 30.0


async def test_fundamentals_context_empty_when_isin_unresolved(monkeypatch):
    p = _provider()

    async def fake_request(path, params=None, limiter=None, base=None):
        raise AssertionError("should not request without an ISIN")

    monkeypatch.setattr(p, "_request", fake_request)
    assert await p.fundamentals_context("NOTLISTED", "IN") == {}


async def test_fundamentals_context_partial_on_bad_income(monkeypatch):
    p = _provider()

    async def fake_request(path, params=None, limiter=None, base=None):
        if "key-ratios" in path:
            return _KEY_RATIOS
        return None  # income-statement unavailable

    monkeypatch.setattr(p, "_request", fake_request)
    out = await p.fundamentals_context("TESTCO", "IN")
    assert out["pe_ratio"] == 20.15
    assert "eps_yoy_pct" not in out  # gracefully absent


async def test_get_ohlc_uses_v3_endpoint(monkeypatch):
    p = _provider()
    calls: list[tuple[str, str | None]] = []

    async def fake_request(path, params=None, limiter=None, base=None):
        calls.append((path, base))
        return {"status": "success", "data": {"candles": [
            ["2025-01-02T00:00:00+05:30", 100, 110, 95, 105, 1000, 0],
        ]}}

    monkeypatch.setattr(p, "_request", fake_request)
    bars = await p.get_ohlc("TESTCO", "IN", "1d", date(2025, 1, 1), date(2025, 1, 3))
    assert len(bars) == 1
    assert calls and "/days/1/" in calls[0][0]
    assert calls[0][1] == _V3_BASE


async def test_get_ohlc_empty_when_unresolved(monkeypatch):
    p = _provider()

    async def fake_request(path, params=None, limiter=None, base=None):
        raise AssertionError("should not request an unresolved instrument")

    monkeypatch.setattr(p, "_request", fake_request)
    assert await p.get_ohlc("NOTLISTED", "IN", "1d", date(2025, 1, 1), date(2025, 1, 3)) == []

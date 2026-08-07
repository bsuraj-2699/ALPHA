"""InstrumentMaster resolver tests (offline; fetcher injected)."""

from __future__ import annotations

import gzip
import json

from packages.data.providers.upstox_instruments import (
    InstrumentMaster,
    normalize_symbol,
)

_NSE_ROWS = [
    {
        "segment": "NSE_EQ",
        "isin": "INE917I01010",
        "trading_symbol": "BAJAJ-AUTO",
        "instrument_key": "NSE_EQ|INE917I01010",
        "name": "Bajaj Auto Ltd",
    },
    {
        "segment": "NSE_EQ",
        "isin": "INE081A01020",
        "trading_symbol": "TATASTEEL",
        "instrument_key": "NSE_EQ|INE081A01020",
        "name": "Tata Steel Ltd",
    },
    # Non-equity row must be ignored.
    {"segment": "NSE_FO", "isin": "X", "trading_symbol": "NIFTY", "instrument_key": "k"},
]
_BSE_ROWS = [
    {
        "segment": "BSE_EQ",
        "isin": "INE917I01010",
        "trading_symbol": "BAJAJ-AUTO",
        "instrument_key": "BSE_EQ|INE917I01010",
        "name": "Bajaj Auto Ltd",
    },
    {
        "segment": "BSE_EQ",
        "isin": "INE668F01031",
        "trading_symbol": "ONLYBSE",
        "instrument_key": "BSE_EQ|INE668F01031",
        "name": "Only On BSE Ltd",
    },
]


def _master(nse=_NSE_ROWS, bse=_BSE_ROWS) -> InstrumentMaster:
    async def _fetch(url: str) -> bytes:
        rows = nse if "NSE" in url else bse
        return gzip.compress(json.dumps(rows).encode())

    return InstrumentMaster(cache=None, fetcher=_fetch)


def test_normalize_symbol():
    assert normalize_symbol("BAJAJ-AUTO") == "BAJAJAUTO"
    assert normalize_symbol("BAJAJAUTO") == "BAJAJAUTO"
    assert normalize_symbol("M&M") == "MM"
    assert normalize_symbol("RELIANCE.NS") == "RELIANCE"


async def test_resolves_hyphenated_symbol_from_internal_form():
    m = _master()
    info = await m.resolve("BAJAJAUTO")  # internal form, no hyphen
    assert info is not None
    assert info.instrument_key == "NSE_EQ|INE917I01010"
    assert info.symbol == "BAJAJ-AUTO"
    assert await m.resolve_isin("BAJAJAUTO") == "INE917I01010"


async def test_prefers_nse_over_bse_when_dual_listed():
    m = _master()
    info = await m.resolve("BAJAJ-AUTO")
    assert info is not None and info.exchange == "NSE"


async def test_bse_only_symbol_resolves():
    m = _master()
    info = await m.resolve("ONLYBSE")
    assert info is not None and info.instrument_key == "BSE_EQ|INE668F01031"


async def test_non_equity_rows_ignored():
    m = _master()
    assert await m.resolve("NIFTY") is None


async def test_unknown_symbol_returns_none():
    m = _master()
    assert await m.resolve("NOTLISTED") is None


async def test_degrades_gracefully_on_download_failure():
    async def _boom(url: str) -> bytes:
        raise RuntimeError("network down")

    m = InstrumentMaster(cache=None, fetcher=_boom)
    assert await m.resolve("RELIANCE") is None  # no crash

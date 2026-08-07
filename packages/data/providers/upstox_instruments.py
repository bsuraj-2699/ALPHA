"""Upstox instrument-master loader (NSE + BSE equities).

Upstox addresses instruments by ``<SEGMENT>|<ISIN>`` (e.g. ``NSE_EQ|INE002A01018``).
Both the historical-candle API and the Company Fundamentals API need that ISIN,
so resolving *any* NSE/BSE symbol to its ISIN is the foundation for real charts,
quotes, technicals, and fundamentals across every listed equity.

This module downloads Upstox's published instrument master (per-exchange JSON,
falling back to the combined file), filters to cash-equity segments, and builds
a symbol lookup. Symbols are indexed both verbatim and *normalized* (uppercase,
alphanumerics only) so internal forms like ``BAJAJAUTO`` resolve to the exchange
trading symbol ``BAJAJ-AUTO``. NSE is preferred over BSE when a symbol lists on
both. The map is cached in Redis (when available) and in-process for 24h, and
the loader degrades gracefully to the static ticker registry if the download
fails.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from packages.data.providers.cache import RedisCache

logger = logging.getLogger(__name__)

_NSE_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_BSE_URL = "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz"

_EQUITY_SEGMENTS = ("NSE_EQ", "BSE_EQ")
_CACHE_KEY = "upstox:instruments:eq:v1"
_CACHE_TTL = 24 * 60 * 60
_DOWNLOAD_TIMEOUT = 30.0


def normalize_symbol(symbol: str) -> str:
    """Uppercase and strip everything but ``A-Z0-9`` (``BAJAJ-AUTO`` -> ``BAJAJAUTO``)."""
    base = symbol.rsplit(".", 1)[0] if symbol.endswith((".NS", ".BO")) else symbol
    return re.sub(r"[^A-Z0-9]", "", base.upper())


@dataclass(frozen=True)
class InstrumentInfo:
    symbol: str  # exchange trading symbol, e.g. "BAJAJ-AUTO"
    isin: str
    instrument_key: str  # e.g. "NSE_EQ|INE917I01010"
    exchange: str  # "NSE" or "BSE"
    segment: str  # "NSE_EQ" or "BSE_EQ"
    name: str


Fetcher = Callable[[str], Awaitable[bytes]]


async def _http_fetch(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def _decode_instruments(raw: bytes) -> list[dict]:
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    parsed = json.loads(data)
    return parsed if isinstance(parsed, list) else []


class InstrumentMaster:
    """Lazy, cached symbol -> :class:`InstrumentInfo` resolver for NSE/BSE equities."""

    def __init__(
        self,
        cache: RedisCache | None = None,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._cache = cache
        self._fetch = fetcher or _http_fetch
        self._by_norm: dict[str, InstrumentInfo] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return bool(self._by_norm) and (time.monotonic() - self._loaded_at) < _CACHE_TTL

    def _ingest(self, rows: list[dict]) -> None:
        # NSE first so it wins over BSE on setdefault for dual-listed symbols.
        ordered = sorted(rows, key=lambda r: 0 if r.get("segment") == "NSE_EQ" else 1)
        for row in ordered:
            segment = row.get("segment")
            isin = row.get("isin")
            symbol = row.get("trading_symbol") or row.get("tradingsymbol")
            key = row.get("instrument_key")
            if segment not in _EQUITY_SEGMENTS or not isin or not symbol or not key:
                continue
            info = InstrumentInfo(
                symbol=symbol,
                isin=isin,
                instrument_key=key,
                exchange="NSE" if segment == "NSE_EQ" else "BSE",
                segment=segment,
                name=row.get("name") or symbol,
            )
            self._by_norm.setdefault(normalize_symbol(symbol), info)

    async def _load_from_cache(self) -> bool:
        if self._cache is None:
            return False
        try:
            blob = await self._cache.get(_CACHE_KEY)
        except Exception:
            return False
        if not blob:
            return False
        try:
            rows = json.loads(blob)
        except ValueError:
            return False
        self._ingest(rows)
        return bool(self._by_norm)

    async def _download(self) -> list[dict]:
        rows: list[dict] = []
        for url in (_NSE_URL, _BSE_URL):
            try:
                raw = await self._fetch(url)
                rows.extend(_decode_instruments(raw))
            except Exception as e:
                logger.warning("instrument master download failed for %s: %s", url, e)
        return [
            {
                "segment": r.get("segment"),
                "isin": r.get("isin"),
                "trading_symbol": r.get("trading_symbol") or r.get("tradingsymbol"),
                "instrument_key": r.get("instrument_key"),
                "name": r.get("name"),
            }
            for r in rows
            if r.get("segment") in _EQUITY_SEGMENTS
        ]

    async def ensure_loaded(self) -> None:
        if self._fresh():
            return
        async with self._lock:
            if self._fresh():
                return
            self._by_norm = {}
            if await self._load_from_cache():
                self._loaded_at = time.monotonic()
                logger.info("instrument master loaded from cache (%d symbols)", len(self._by_norm))
                return
            rows = await self._download()
            if not rows:
                logger.warning("instrument master empty; falling back to static registry")
                return
            self._ingest(rows)
            self._loaded_at = time.monotonic()
            if self._cache is not None:
                with contextlib.suppress(Exception):
                    await self._cache.set(_CACHE_KEY, json.dumps(rows), _CACHE_TTL)
            logger.info("instrument master loaded (%d equities)", len(self._by_norm))

    async def resolve(self, symbol: str) -> InstrumentInfo | None:
        await self.ensure_loaded()
        return self._by_norm.get(normalize_symbol(symbol))

    async def resolve_isin(self, symbol: str) -> str | None:
        info = await self.resolve(symbol)
        return info.isin if info else None

    async def resolve_instrument_key(self, symbol: str) -> str | None:
        info = await self.resolve(symbol)
        return info.instrument_key if info else None


_singleton: InstrumentMaster | None = None


def get_instrument_master(cache: RedisCache | None = None) -> InstrumentMaster:
    """Process-wide :class:`InstrumentMaster` singleton."""
    global _singleton
    if _singleton is None:
        _singleton = InstrumentMaster(cache=cache)
    return _singleton


__all__ = [
    "InstrumentInfo",
    "InstrumentMaster",
    "get_instrument_master",
    "normalize_symbol",
]

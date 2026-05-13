"""Price endpoint — real OHLC for the analyze-page chart.

```
GET /api/price/{ticker}?market=IN&interval=1d&lookback_days=200
```

Resolves data through the same provider stack the orchestrator uses:
Upstox first (when credentials are configured), Yahoo Finance as the
fallback — **except** for NSE headline index symbols (``NIFTY``,
``BANKNIFTY``, ``FINNIFTY``, ``MIDCPNIFTY``), where Yahoo is tried first
so yfinance maps to ``^NSEI`` / ``^NSEBANK`` / … instead of Upstox
resolving ``NSE_EQ|NIFTY`` to the wrong equity.

Returns a tight wire-shape (`PriceBar` is just six numbers
per candle) so the chart doesn't have to deserialize the full
`OHLCBar` schema with Decimals.

Caching
-------
Each provider already memoises against Redis with a 5-minute TTL on
OHLC and 5-second TTL on quotes, so repeated UI fetches don't
re-hammer Upstox. We additionally cache the *assembled response* for
60 seconds in-process so the chart can poll without round-tripping
the provider chain on every refresh interval.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from apps.api.models import Market, PriceBar, PriceInterval, PriceQuote, PriceResponse
from packages.data.providers.base import MarketDataProvider
from packages.shared.schemas import OHLCBar, Quote

logger = logging.getLogger(__name__)
router = APIRouter()

# NSE headline index tickers. Upstox ``NSE_EQ|NIFTY`` is
# not the Nifty 50 index; Yahoo maps these to ``^NSEI`` etc. (see
# ``YahooFinanceProvider._normalize_ticker``).
_HEADLINE_IN_INDEX_TICKERS: frozenset[str] = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
)


# ---------------------------------------------------------------------------
# Provider plumbing
# ---------------------------------------------------------------------------


def _ordered_price_providers(
    providers: list[MarketDataProvider],
    ticker: str,
    market: Market,
) -> list[MarketDataProvider]:
    """Return a copy; put Yahoo first for headline indices on IN only."""
    if market != "IN" or ticker not in _HEADLINE_IN_INDEX_TICKERS:
        return list(providers)
    return sorted(
        providers,
        key=lambda p: 0 if getattr(p, "name", "") == "yahoo" else 1,
    )




def _build_providers_for(market: Market) -> list[MarketDataProvider]:
    """Mirror of `_build_default_providers` that only constructs price-capable
    providers. Upstox first for IN (when creds are present), Yahoo always."""
    providers: list[MarketDataProvider] = []
    if market == "IN" and os.getenv("UPSTOX_API_KEY") and os.getenv("UPSTOX_API_SECRET"):
        try:
            from packages.data.providers.upstox import UpstoxProvider

            providers.append(UpstoxProvider())
        except (ImportError, RuntimeError) as e:
            logger.info("Upstox unavailable for price endpoint: %s", e)
    try:
        from packages.data.providers.yahoo import YahooFinanceProvider

        providers.append(YahooFinanceProvider())
    except ImportError as e:
        logger.info("Yahoo unavailable for price endpoint: %s", e)
    return providers


def _get_or_build_providers(request: Request, market: Market) -> list[MarketDataProvider]:
    """Cache the provider list on `app.state` so repeated requests don't
    re-instantiate the HTTP clients."""
    cache: dict[Market, list[MarketDataProvider]] = getattr(
        request.app.state, "_price_providers", {}
    )
    if market not in cache:
        cache[market] = _build_providers_for(market)
        request.app.state._price_providers = cache
    return cache[market]


# ---------------------------------------------------------------------------
# In-process response cache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _CachedResponse:
    payload: PriceResponse
    expires_at: float


_RESPONSE_CACHE: dict[str, _CachedResponse] = {}
_RESPONSE_TTL_SECONDS = 60.0


def _cache_key(ticker: str, market: Market, interval: str, lookback_days: int) -> str:
    return f"{market}:{ticker.upper()}:{interval}:{lookback_days}"


def _cache_get(key: str) -> PriceResponse | None:
    rec = _RESPONSE_CACHE.get(key)
    if rec is None:
        return None
    if rec.expires_at < time.monotonic():
        _RESPONSE_CACHE.pop(key, None)
        return None
    return rec.payload


def _cache_set(key: str, payload: PriceResponse) -> None:
    _RESPONSE_CACHE[key] = _CachedResponse(
        payload=payload, expires_at=time.monotonic() + _RESPONSE_TTL_SECONDS
    )


# ---------------------------------------------------------------------------
# Synthetic last-resort fallback
# ---------------------------------------------------------------------------


def _synthetic_bars(ticker: str, lookback_days: int) -> list[PriceBar]:
    """Deterministic placeholder so the UI is never empty during outages.

    The shape is intentionally simple — a slow random-walk seeded from
    the ticker hash. Marked `stale=True` on the response so the UI can
    overlay an "estimate only" banner.
    """
    import hashlib
    import math

    seed = int(hashlib.md5(ticker.upper().encode()).hexdigest()[:8], 16)
    base = 100.0 + (seed % 9000) / 10.0
    bars: list[PriceBar] = []
    today = date.today()
    for i in range(lookback_days):
        d = today - timedelta(days=lookback_days - i)
        # Pseudo-random walk with bounded drift.
        x = (seed + i * 9301) % 233280
        drift = ((x / 233280.0) - 0.5) * 0.04
        base = max(1.0, base * (1.0 + drift))
        wick = base * 0.012
        bars.append(
            PriceBar(
                time=int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()),
                open=round(base * (1 + math.copysign(wick * 0.4, drift) / base), 2),
                high=round(base + wick, 2),
                low=round(base - wick, 2),
                close=round(base, 2),
                volume=0,
            )
        )
    return bars


# ---------------------------------------------------------------------------
# Provider loop
# ---------------------------------------------------------------------------


_PROVIDER_TIMEOUT = 6.0  # seconds per provider attempt


async def _try_ohlc(
    provider: MarketDataProvider,
    ticker: str,
    market: Market,
    interval: PriceInterval,
    start: date,
    end: date,
) -> list[OHLCBar]:
    return await asyncio.wait_for(
        provider.get_ohlc(ticker, market, interval, start, end),
        timeout=_PROVIDER_TIMEOUT,
    )


async def _try_quote(
    provider: MarketDataProvider, ticker: str, market: Market
) -> Quote | None:
    try:
        return await asyncio.wait_for(
            provider.get_quote(ticker, market), timeout=_PROVIDER_TIMEOUT
        )
    except Exception:
        return None


def _bars_to_wire(bars: list[OHLCBar]) -> list[PriceBar]:
    out: list[PriceBar] = []
    for b in bars:
        ts = b.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        out.append(
            PriceBar(
                time=int(ts.timestamp()),
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=int(b.volume or 0),
            )
        )
    out.sort(key=lambda x: x.time)
    return out


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/price/{ticker}", response_model=PriceResponse)
async def get_price(
    request: Request,
    ticker: str,
    market: Market = Query("IN"),
    interval: PriceInterval = Query("1d"),
    lookback_days: int = Query(200, ge=2, le=2000),
) -> PriceResponse:
    """Real OHLC + spot quote for `ticker`.

    Provider waterfall (per market): Upstox → Yahoo → synthetic. The
    chosen source is echoed in the response under `source`.
    """
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 20:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    cache_key = _cache_key(ticker, market, interval, lookback_days)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    providers = _ordered_price_providers(
        _get_or_build_providers(request, market),
        ticker,
        market,
    )
    end = date.today()
    start = end - timedelta(days=lookback_days)

    bars: list[PriceBar] = []
    quote_obj: Quote | None = None
    source = "synthetic"

    for provider in providers:
        if market not in getattr(provider, "supported_markets", ()):
            continue
        try:
            raw = await _try_ohlc(provider, ticker, market, interval, start, end)
        except asyncio.TimeoutError:
            logger.warning("price: %s timed out for %s", provider.name, ticker)
            continue
        except Exception as e:
            logger.info("price: %s failed for %s: %s", provider.name, ticker, e)
            continue
        if raw:
            bars = _bars_to_wire(raw)
            source = provider.name
            quote_obj = await _try_quote(provider, ticker, market)
            break

    stale = False
    if not bars:
        bars = _synthetic_bars(ticker, lookback_days)
        stale = True

    currency = "INR" if market == "IN" else "USD"
    if quote_obj is not None:
        quote_payload: PriceQuote | None = PriceQuote(
            price=float(quote_obj.price),
            change_pct=quote_obj.change_pct,
            currency=quote_obj.currency or currency,
            timestamp=quote_obj.timestamp,
        )
        currency = quote_obj.currency or currency
    elif bars:
        last = bars[-1]
        prev = bars[-2] if len(bars) >= 2 else None
        change_pct = (
            ((last.close - prev.close) / prev.close * 100.0)
            if prev and prev.close
            else None
        )
        quote_payload = PriceQuote(
            price=last.close,
            change_pct=change_pct,
            currency=currency,
            timestamp=datetime.fromtimestamp(last.time, tz=UTC),
        )
    else:
        quote_payload = None

    payload = PriceResponse(
        ticker=ticker,
        market=market,
        interval=interval,
        currency=currency,
        bars=bars,
        quote=quote_payload,
        source=source,
        stale=stale,
    )
    _cache_set(cache_key, payload)
    return payload


# Suppress unused import warning — kept for the type alias side-effect.
_ = Any

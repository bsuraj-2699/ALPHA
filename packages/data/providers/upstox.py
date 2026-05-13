"""Upstox REST adapter (Indian market data).

Implements the MarketDataProvider protocol for IN equities. Quotes and OHLC
candles come from Upstox v2 endpoints; fundamentals/news are not exposed by
Upstox so they delegate to other providers (Screener, GDELT) via the
ContextBuilder. Corporate actions (dividends, splits) are fetched from the
``/corporate-actions`` endpoint.

Auth
----
``UPSTOX_API_KEY``, ``UPSTOX_API_SECRET`` and an initial
``UPSTOX_ACCESS_TOKEN`` come from the environment. The access token is
refreshed daily by ``upstox_auth.refresh_access_token`` (called from the
FastAPI startup hook) and written to Redis under ``upstox:access_token``.
This provider always reads the token from Redis first, falling back to the
env var only on the first call before the daily refresh has run.

Instrument keys
---------------
Upstox addresses instruments by ``NSE_EQ|<ISIN>`` (preferred) or
``NSE_EQ|<symbol>``. ``symbol_to_instrument_key`` resolves either form. A
small built-in ISIN map covers the most common NSE symbols; production
deployments should load the full instrument master from
``https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz``.

Rate limits
-----------
Upstox publishes 25 req/sec overall. We split the budget per the user spec:
10 req/s for historical candles, 5 req/s for live quotes — using two
RateLimiter instances so the two surfaces do not starve each other.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx

from packages.data.providers.base import MarketDataProvider, OHLCInterval
from packages.data.providers.cache import RedisCache
from packages.data.providers.rate_limit import RateLimiter
from packages.shared.schemas import (
    CorporateAction,
    Fundamentals,
    Market,
    NewsItem,
    OHLCBar,
    Quote,
)

logger = logging.getLogger(__name__)


_BASE = "https://api.upstox.com/v2"
_TIMEOUT = 8.0
_QUOTE_TTL = 5
_OHLC_TTL = 5 * 60
_CA_TTL = 6 * 60 * 60

_INTERVAL_MAP: dict[str, str] = {
    # Provider-internal short form → Upstox v2 historical-candle API value.
    # Valid Upstox values per UDAPI1020: 1minute, 30minute, day, week, month.
    # The v2 historical-candle API does NOT support 5/15/60-minute intervals
    # — those are intraday-feed-only and require a separate endpoint.
    "1m":  "1minute",
    "30m": "30minute",
    "1d":  "day",
    "1wk": "week",
    "1mo": "month",
    # Aliases for unsupported intervals — fall back to nearest valid value.
    # Callers asking for 5m / 15m / 1h on historical-candle endpoint will
    # silently receive 1minute or 30minute bars; the technicals block
    # always asks for "1d" anyway so this only affects edge cases.
    "5m":  "1minute",
    "15m": "30minute",
    "1h":  "30minute",
    "60m": "30minute",
}

# Minimal seed map: bare NSE symbol → ISIN. Production should load the full
# instrument master CSV.
_DEFAULT_ISINS: dict[str, str] = {
    "RELIANCE": "INE002A01018",
    "TCS": "INE467B01029",
    "HDFCBANK": "INE040A01034",
    "INFY": "INE009A01021",
    "ICICIBANK": "INE090A01021",
    "SBIN": "INE062A01020",
    "LT": "INE018A01030",
    "ITC": "INE154A01025",
    "HINDUNILVR": "INE030A01027",
    "AXISBANK": "INE238A01034",
}


def _strip_suffix(ticker: str) -> str:
    if ticker.endswith((".NS", ".BO")):
        return ticker.rsplit(".", 1)[0]
    return ticker


def symbol_to_instrument_key(symbol: str, isin_map: dict[str, str] | None = None) -> str:
    """Resolve a ticker to an Upstox instrument key.

    Accepts ``RELIANCE``, ``RELIANCE.NS``, or an already-formed
    ``NSE_EQ|INE002A01018`` and returns a key Upstox will accept.

    Resolution order:
      1. Already a fully-formed key (contains ``|``) → return as-is.
      2. Found in caller-supplied or ``_DEFAULT_ISINS`` map → return ``NSE_EQ|<ISIN>``.
      3. Found in ``packages.shared.ticker_registry`` (Nifty 50 + Next 50) → return that key.
      4. Symbol-based fallback ``NSE_EQ|<SYMBOL>`` (works for LTP, may fail for historical candles).
    """
    if "|" in symbol:
        return symbol
    bare = _strip_suffix(symbol)
    # Index symbols (Upstox uses a different namespace than NSE_EQ).
    # This is required for historical candles used by ContextBuilder's
    # NIFTY 50 SMA helper.
    if bare in ("NIFTY", "NIFTY50", "NIFTY_50", "NIFTY-50"):
        return "NSE_INDEX|Nifty 50"
    table = isin_map if isin_map is not None else _DEFAULT_ISINS
    isin = table.get(bare)
    if isin:
        return f"NSE_EQ|{isin}"
    # Try the global ticker_registry next — covers Nifty 50 + Next 50 ISINs
    # which Upstox's historical-candle API requires (symbol-based keys often
    # 404 on /historical-candle/ even for liquid names).
    try:
        from packages.shared.ticker_registry import to_upstox
        return to_upstox(bare)
    except ImportError:
        pass
    # Final fallback: symbol-based key. Upstox accepts this for many liquid
    # names on LTP but may 404 on historical candles.
    return f"NSE_EQ|{bare}"


class UpstoxProvider(MarketDataProvider):
    name = "upstox"
    supported_markets: tuple[Market, ...] = ("IN",)

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        access_token: str | None = None,
        cache: RedisCache | None = None,
        quote_limiter: RateLimiter | None = None,
        historical_limiter: RateLimiter | None = None,
        isin_map: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("UPSTOX_API_KEY")
        self.api_secret = api_secret or os.getenv("UPSTOX_API_SECRET")
        # The env-supplied token is only the bootstrap value; the live one
        # lives in Redis after the daily refresh runs.
        self._env_token = access_token or os.getenv("UPSTOX_ACCESS_TOKEN")
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "Upstox credentials missing — set UPSTOX_API_KEY and UPSTOX_API_SECRET"
            )
        self.cache = cache if cache is not None else RedisCache()
        self.quote_limiter = quote_limiter or RateLimiter.per_second(5)
        self.historical_limiter = historical_limiter or RateLimiter.per_second(10)
        self._isin_map = dict(_DEFAULT_ISINS)
        if isin_map:
            self._isin_map.update(isin_map)

    def register_isin(self, symbol: str, isin: str) -> None:
        self._isin_map[_strip_suffix(symbol)] = isin

    def _instrument_key(self, ticker: str) -> str:
        return symbol_to_instrument_key(ticker, self._isin_map)

    async def _access_token(self) -> str:
        token = await self.cache.get("upstox:access_token")
        if token:
            return token
        if self._env_token:
            return self._env_token
        raise RuntimeError(
            "No Upstox access token available — daily refresh has not run "
            "and UPSTOX_ACCESS_TOKEN is not set."
        )

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None,
        limiter: RateLimiter,
    ) -> dict[str, Any] | None:
        await limiter.acquire()
        token = await self._access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{_BASE}{path}", params=params, headers=headers)
        except (httpx.HTTPError, OSError) as e:
            logger.warning("upstox %s failed: %s", path, e)
            return None
        if resp.status_code in (401, 403):
            logger.warning("upstox %s auth rejected (status=%d)", path, resp.status_code)
            return None
        if resp.status_code >= 400:
            logger.warning(
                "upstox %s status=%d body=%s", path, resp.status_code, resp.text[:200]
            )
            return None
        try:
            return resp.json()
        except ValueError:
            logger.warning("upstox %s returned non-JSON", path)
            return None

    # ------------------------------------------------------------------ quote
    async def get_quote(self, ticker: str, market: Market) -> Quote:
        if market != "IN":
            raise ValueError(f"UpstoxProvider does not support market {market}")
        cache_key = f"upstox:quote:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Quote.model_validate_json(cached)

        instrument = self._instrument_key(ticker)
        data = await self._request(
            "/market-quote/ltp",
            {"instrument_key": instrument},
            self.quote_limiter,
        )
        if not data or data.get("status") != "success":
            raise RuntimeError(f"upstox ltp failed for {ticker}: {data}")
        records = data.get("data") or {}
        # The response keys back the instrument as "NSE_EQ:<symbol>" — pick the
        # first record rather than guessing the exact form.
        record = next(iter(records.values()), None) if records else None
        if not record:
            raise RuntimeError(f"upstox ltp returned no record for {ticker}")
        last_price = float(record.get("last_price") or 0.0)

        quote = Quote(
            ticker=ticker,
            market="IN",
            price=Decimal(str(last_price)),
            currency="INR",
            timestamp=datetime.now(UTC),
            change_pct=None,
            volume=None,
        )
        await self.cache.set(cache_key, quote.model_dump_json(), _QUOTE_TTL)
        return quote

    # ------------------------------------------------------------------ ohlc
    async def get_ohlc(
        self,
        ticker: str,
        market: Market,
        interval: OHLCInterval,
        start: date,
        end: date,
    ) -> list[OHLCBar]:
        if market != "IN":
            raise ValueError(f"UpstoxProvider does not support market {market}")
        cache_key = f"upstox:ohlc:{ticker}:{interval}:{start}:{end}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [OHLCBar.model_validate(b) for b in json.loads(cached)]

        upstox_interval = _INTERVAL_MAP.get(interval, interval)
        instrument = self._instrument_key(ticker)
        path = f"/historical-candle/{instrument}/{upstox_interval}/{end.isoformat()}/{start.isoformat()}"
        logger.info(
            "upstox get_ohlc: ticker=%s instrument=%s interval=%s→%s start=%s end=%s",
            ticker, instrument, interval, upstox_interval, start, end,
        )
        data = await self._request(path, None, self.historical_limiter)
        if not data or data.get("status") != "success":
            logger.warning(
                "upstox get_ohlc returned no data for %s (instrument=%s, interval=%s)",
                ticker, instrument, upstox_interval,
            )
            return []

        candles = (data.get("data") or {}).get("candles") or []
        logger.info("upstox get_ohlc: %s returned %d candles", ticker, len(candles))
        # Upstox candle row: [timestamp, open, high, low, close, volume, oi]
        bars: list[OHLCBar] = []
        for row in candles:
            try:
                ts = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            except (TypeError, ValueError, AttributeError):
                continue
            try:
                bars.append(
                    OHLCBar(
                        ticker=ticker,
                        timestamp=ts,
                        open=Decimal(str(row[1])),
                        high=Decimal(str(row[2])),
                        low=Decimal(str(row[3])),
                        close=Decimal(str(row[4])),
                        volume=int(row[5] or 0),
                        interval=cast(Any, interval),
                    )
                )
            except (IndexError, ValueError):
                continue
        bars.sort(key=lambda b: b.timestamp)

        await self.cache.set(
            cache_key,
            json.dumps([b.model_dump(mode="json") for b in bars], default=str),
            _OHLC_TTL,
        )
        return bars

    # --------------------------------------------------------- fundamentals
    async def get_fundamentals(self, ticker: str, market: Market) -> Fundamentals:
        # Upstox does not publish fundamentals; the ContextBuilder routes
        # this request to ScreenerProvider instead.
        raise NotImplementedError(
            "Upstox does not expose fundamentals — use ScreenerProvider."
        )

    # ----------------------------------------------------------------- news
    async def get_news(
        self, ticker: str, market: Market, lookback_days: int = 14
    ) -> list[NewsItem]:
        # Upstox does not publish news; GDELT/NSE handle this surface.
        return []

    # ---------------------------------------------------- corporate actions
    async def get_corporate_actions(
        self, ticker: str, market: Market, lookback_days: int = 365
    ) -> list[CorporateAction]:
        if market != "IN":
            raise ValueError(f"UpstoxProvider does not support market {market}")
        instrument = self._instrument_key(ticker)
        cache_key = f"upstox:ca:{ticker}:{lookback_days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [CorporateAction.model_validate(a) for a in json.loads(cached)]

        from_date = (date.today() - timedelta(days=lookback_days)).isoformat()
        to_date = date.today().isoformat()
        data = await self._request(
            "/corporate-actions",
            {"instrument_key": instrument, "from_date": from_date, "to_date": to_date},
            self.historical_limiter,
        )
        if not data or data.get("status") != "success":
            return []

        rows = data.get("data") or []
        actions: list[CorporateAction] = []
        for r in rows:
            kind_raw = str(r.get("purpose") or r.get("action_type") or "").lower()
            if "dividend" in kind_raw:
                kind = "dividend"
            elif "split" in kind_raw:
                kind = "split"
            elif "buyback" in kind_raw:
                kind = "buyback"
            elif "bonus" in kind_raw:
                kind = "bonus"
            elif "rights" in kind_raw:
                kind = "rights"
            else:
                continue
            try:
                ex_d = date.fromisoformat(r["ex_date"])
            except (KeyError, ValueError):
                continue
            try:
                rec_d = date.fromisoformat(r["record_date"]) if r.get("record_date") else None
            except ValueError:
                rec_d = None
            details: dict[str, str | float | int] = {}
            for k in ("ratio", "dividend", "face_value", "purpose"):
                v = r.get(k)
                if v is not None:
                    details[k] = v if isinstance(v, (int, float, str)) else str(v)
            actions.append(
                CorporateAction(
                    ticker=ticker,
                    action_type=cast(Any, kind),
                    ex_date=ex_d,
                    record_date=rec_d,
                    details=details,
                )
            )

        await self.cache.set(
            cache_key,
            json.dumps([a.model_dump(mode="json") for a in actions], default=str),
            _CA_TTL,
        )
        return actions


__all__ = ["UpstoxProvider", "symbol_to_instrument_key"]
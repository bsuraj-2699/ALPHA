"""Upstox REST adapter (Indian market data).

Implements the MarketDataProvider protocol for IN equities. Quotes come from
the v2 market-quote endpoint and OHLC candles from the v3 historical-candle API
(with a v2 fallback). Fundamentals/valuation come from the Upstox Company
Fundamentals API (ISIN-keyed key-ratios + income-statement) exposed via
``fundamentals_context`` and merged at top priority by the ContextBuilder; news
still delegates to GDELT. Corporate actions (dividends, splits) are fetched from
the ``/corporate-actions`` endpoint.

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
Upstox addresses instruments by ``<SEGMENT>|<ISIN>`` (e.g. ``NSE_EQ|INE002A01018``).
``_resolve_key`` consults the full instrument master (``upstox_instruments``,
covering all NSE + BSE equities, authoritative and fresh) first, then the static
seed map / ticker registry as an offline fallback. It never emits a symbol-based
guess, so unknown symbols cleanly defer to another provider.

Rate limits
-----------
Upstox publishes 25 req/sec overall. We split the budget per the user spec:
10 req/s for historical candles, 5 req/s for live quotes — using two
RateLimiter instances so the two surfaces do not starve each other.
"""

from __future__ import annotations

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
from packages.data.providers.upstox_instruments import (
    InstrumentMaster,
    get_instrument_master,
)
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
_V3_BASE = "https://api.upstox.com/v3"
_FUND_TTL = 12 * 60 * 60
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

# Upstox v3 historical-candle API: /historical-candle/{key}/{unit}/{interval}/...
# The v3 API (unlike v2) accepts 5/15-minute units and is the current endpoint;
# we prefer it and fall back to v2 for resilience.
_V3_INTERVAL: dict[str, tuple[str, str]] = {
    "1m":  ("minutes", "1"),
    "5m":  ("minutes", "5"),
    "15m": ("minutes", "15"),
    "30m": ("minutes", "30"),
    "1h":  ("hours", "1"),
    "60m": ("hours", "1"),
    "1d":  ("days", "1"),
    "1wk": ("weeks", "1"),
    "1mo": ("months", "1"),
}

_INDEX_SYMBOLS: frozenset[str] = frozenset(
    {"NIFTY", "NIFTY50", "NIFTY_50", "NIFTY-50"}
)

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


def _parse_num(value: Any) -> float | None:
    """Parse an Upstox fundamentals value (``"12.46"``/``"7.54%"``/number)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").rstrip("%")
    if not s or s in ("-", "NA", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct_change(latest: float | None, prior: float | None) -> float | None:
    if latest is None or prior is None or prior == 0:
        return None
    return round((latest - prior) / abs(prior) * 100.0, 2)


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


def _offline_isin_key(symbol: str, isin_map: dict[str, str] | None = None) -> str | None:
    """Resolve to an ISIN-form key from the seed map / registry only.

    Returns ``None`` (rather than a symbol-based guess) when the symbol is not
    known offline, so callers can consult the instrument master instead of
    firing a request that 404s on historical candles.
    """
    if "|" in symbol:
        return symbol
    bare = _strip_suffix(symbol)
    if bare in _INDEX_SYMBOLS:
        return "NSE_INDEX|Nifty 50"
    table = isin_map if isin_map is not None else _DEFAULT_ISINS
    isin = table.get(bare)
    if isin:
        return f"NSE_EQ|{isin}"
    try:
        from packages.shared.ticker_registry import is_known, to_upstox

        # ``to_upstox`` falls back to a symbol-based guess; only trust it for
        # registered tickers so unknown symbols defer to the instrument master.
        if is_known(bare):
            return to_upstox(bare)
    except ImportError:
        pass
    return None


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
        instrument_master: InstrumentMaster | None = None,
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
        self._master = instrument_master or get_instrument_master(self.cache)

    def register_isin(self, symbol: str, isin: str) -> None:
        self._isin_map[_strip_suffix(symbol)] = isin

    async def _resolve_key(self, ticker: str) -> str | None:
        """Resolve to an Upstox instrument key: master -> seed/registry -> None.

        The instrument master is authoritative and fresh, so it is consulted
        first — this corrects stale ISINs baked into the static registry (e.g.
        after a split changes a company's ISIN). The seed/registry is only the
        offline fallback when the master cannot load. Never returns a
        symbol-based guess; ``None`` means "not resolvable", so callers can skip
        Upstox and let another provider serve the request.
        """
        if "|" in ticker:
            return ticker
        bare = _strip_suffix(ticker)
        if bare in _INDEX_SYMBOLS:
            return "NSE_INDEX|Nifty 50"
        try:
            key = await self._master.resolve_instrument_key(ticker)
        except Exception as e:  # pragma: no cover - network/parse guard
            logger.warning("instrument master resolve failed for %s: %s", ticker, e)
            key = None
        if key:
            return key
        return _offline_isin_key(ticker, self._isin_map)

    async def _resolve_isin(self, ticker: str) -> str | None:
        """ISIN for ``ticker`` (for the ISIN-keyed fundamentals API)."""
        key = await self._resolve_key(ticker)
        if key and "|" in key:
            candidate = key.split("|", 1)[1]
            if candidate.startswith("INE") or candidate.startswith("INF"):
                return candidate
        try:
            return await self._master.resolve_isin(ticker)
        except Exception:  # pragma: no cover
            return None

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
        base: str = _BASE,
    ) -> dict[str, Any] | None:
        await limiter.acquire()
        token = await self._access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(f"{base}{path}", params=params, headers=headers)
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

        instrument = await self._resolve_key(ticker)
        if not instrument:
            raise RuntimeError(f"upstox could not resolve instrument for {ticker}")
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

    async def _historical_candle(
        self, instrument: str, interval: OHLCInterval, start: date, end: date
    ) -> dict[str, Any] | None:
        """Fetch candles via the v3 API, falling back to v2 on failure."""
        v3 = _V3_INTERVAL.get(interval)
        if v3 is not None:
            unit, mult = v3
            path = (
                f"/historical-candle/{instrument}/{unit}/{mult}"
                f"/{end.isoformat()}/{start.isoformat()}"
            )
            data = await self._request(
                path, None, self.historical_limiter, base=_V3_BASE
            )
            if data and data.get("status") == "success":
                return data
        # v2 fallback (older interval vocabulary).
        v2_interval = _INTERVAL_MAP.get(interval, interval)
        path = (
            f"/historical-candle/{instrument}/{v2_interval}"
            f"/{end.isoformat()}/{start.isoformat()}"
        )
        return await self._request(path, None, self.historical_limiter)

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

        instrument = await self._resolve_key(ticker)
        if not instrument:
            logger.warning("upstox get_ohlc: could not resolve instrument for %s", ticker)
            return []
        logger.info(
            "upstox get_ohlc: ticker=%s instrument=%s interval=%s start=%s end=%s",
            ticker, instrument, interval, start, end,
        )
        data = await self._historical_candle(instrument, interval, start, end)
        if not data or data.get("status") != "success":
            logger.warning(
                "upstox get_ohlc returned no data for %s (instrument=%s, interval=%s)",
                ticker, instrument, interval,
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
    async def _fundamentals_endpoint(self, isin: str, name: str, **params: str) -> Any:
        data = await self._request(
            f"/fundamentals/{isin}/{name}", params or None, self.historical_limiter
        )
        if not data:
            return None
        return data.get("data", data)

    async def fundamentals_context(self, ticker: str, market: Market) -> dict[str, Any]:
        """Context-key fundamentals/valuation from the Upstox Company Fundamentals
        API (ISIN-keyed). Returns only the keys it could resolve; missing metrics
        are left for the Screener/Yahoo fallback to fill.
        """
        if market != "IN":
            return {}
        isin = await self._resolve_isin(ticker)
        if not isin:
            return {}
        cache_key = f"upstox:fund:{isin}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cast(dict[str, Any], json.loads(cached))

        out: dict[str, Any] = {}
        try:
            out.update(await self._key_ratios(isin))
        except Exception as e:  # pragma: no cover - defensive parse guard
            logger.warning("upstox key-ratios parse failed for %s: %s", ticker, e)
        try:
            out.update(await self._income_metrics(isin))
        except Exception as e:  # pragma: no cover
            logger.warning("upstox income-statement parse failed for %s: %s", ticker, e)

        if out:
            await self.cache.set(cache_key, json.dumps(out), _FUND_TTL)
        return out

    async def _key_ratios(self, isin: str) -> dict[str, Any]:
        payload = await self._fundamentals_endpoint(isin, "key-ratios", type="consolidated")
        rows = payload if isinstance(payload, list) else (payload or {}).get("ratios") or []
        by_name: dict[str, float | None] = {}
        for row in rows:
            name = str(row.get("name", "")).upper().replace(" ", "")
            by_name[name] = _parse_num(row.get("company_value"))
        mapping = {
            "P/E": "pe_ratio",
            "P/B": "pb_ratio",
            "ROE": "roe_pct",
            "ROA": "roa_pct",
            "EV/EBITDA": "ev_ebitda",
        }
        return {ctx: by_name[src] for src, ctx in mapping.items() if by_name.get(src) is not None}

    async def _income_metrics(self, isin: str) -> dict[str, Any]:
        payload = await self._fundamentals_endpoint(
            isin, "income-statement", type="consolidated", time_period="yearly", fs="true"
        )
        if not isinstance(payload, dict):
            return {}
        out: dict[str, Any] = {}

        def _history(rows: list[dict], match: str, field: str = "category") -> list[float]:
            for row in rows:
                if match in str(row.get(field, "")).lower():
                    return [
                        v for v in (_parse_num(h.get("value")) for h in row.get("history", []))
                        if v is not None
                    ]
            return []

        statement = payload.get("income_statement") or []
        revenue = _history(statement, "revenue")
        net_profit = _history(statement, "net_profit") or _history(statement, "net profit")
        if len(revenue) >= 2:
            out["revenue_yoy_pct"] = _pct_change(revenue[0], revenue[1])
        if revenue and net_profit and revenue[0]:
            out["net_margin_current"] = round(net_profit[0] / revenue[0] * 100.0, 2)
        if len(revenue) >= 3 and len(net_profit) >= 3 and revenue[2]:
            out["net_margin_2q_ago"] = round(net_profit[2] / revenue[2] * 100.0, 2)

        full = payload.get("full_statement") or []
        eps = _history(full, "eps", field="particular")
        if len(eps) >= 2:
            out["eps_yoy_pct"] = _pct_change(eps[0], eps[1])
        return {k: v for k, v in out.items() if v is not None}

    async def get_fundamentals(self, ticker: str, market: Market) -> Fundamentals:
        # ``get_fundamentals`` stays unimplemented so ContextBuilder's provider
        # chain still reaches Yahoo (for beta / target_price). Upstox fundamentals
        # are surfaced via ``fundamentals_context`` and merged at higher priority.
        raise NotImplementedError(
            "Use UpstoxProvider.fundamentals_context — get_fundamentals is intentionally unset."
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
        instrument = await self._resolve_key(ticker)
        if not instrument:
            return []
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

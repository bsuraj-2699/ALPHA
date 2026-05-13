"""NSE India public-data adapter.

Pulls VIX, FII/DII flows, option-chain PCR and Nifty trend from
``nseindia.com`` JSON endpoints. No API key — but NSE's edge actively
blocks bare requests, so every call goes through a single
``aiohttp.ClientSession`` that has been "warmed" by hitting the homepage
to populate cookies and uses a desktop-Chrome User-Agent.

Outputs feed the macro/risk pillar of the rule engine. Caches:

    VIX        — 5 min
    FII/DII    — 1 h  (only updates once per session close)
    PCR        — 5 min
    Nifty trend — 5 min (the 50-day SMA leg is computed from Upstox candles
                          by the caller, not here)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from packages.data.providers.cache import RedisCache

logger = logging.getLogger(__name__)


_BASE = "https://www.nseindia.com"
_HOME = f"{_BASE}/"
_ALL_INDICES = f"{_BASE}/api/allIndices"
_FII_DII = f"{_BASE}/api/fiidiiTradeReact"
_OPTION_CHAIN = f"{_BASE}/api/option-chain-equities"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_BASE}/",
    "X-Requested-With": "XMLHttpRequest",
}

_TTL_VIX = 5 * 60
_TTL_FII_DII = 60 * 60
_TTL_PCR = 5 * 60
_TTL_INDICES = 5 * 60


class NSEProvider:
    """India-only macro/flow signals from NSE's public JSON endpoints."""

    name = "nse"

    def __init__(self, cache: RedisCache | None = None) -> None:
        self.cache = cache if cache is not None else RedisCache()
        self._session: Any | None = None  # aiohttp.ClientSession
        self._warm = False

    async def _get_session(self) -> Any:
        if self._session is not None:
            return self._session
        try:
            import aiohttp
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("aiohttp required for NSEProvider") from e

        jar = aiohttp.CookieJar(unsafe=True)
        timeout = aiohttp.ClientTimeout(total=10.0)
        session = aiohttp.ClientSession(
            cookie_jar=jar,
            timeout=timeout,
            headers=_HEADERS,
        )
        self._session = session
        return session

    async def _warm_session(self) -> None:
        if self._warm:
            return
        session = await self._get_session()
        try:
            async with session.get(_HOME) as resp:
                await resp.read()
            self._warm = True
        except Exception as e:
            logger.warning("nse session warm-up failed: %s", e)

    async def aclose(self) -> None:
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None
            self._warm = False

    async def _fetch_json(self, url: str, params: dict[str, str] | None = None) -> Any | None:
        await self._warm_session()
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning("nse %s status=%d", url, resp.status)
                    return None
                text = await resp.text()
        except Exception as e:
            logger.warning("nse %s failed: %s", url, e)
            return None
        try:
            return json.loads(text)
        except ValueError:
            logger.warning("nse %s returned non-JSON", url)
            return None

    # ---------------------------------------------------------------- VIX
    async def get_india_vix(self) -> dict[str, Any]:
        cache_key = "nse:vix"
        cached = await self.cache.get(cache_key)
        if cached:
            return json.loads(cached)
        data = await self._fetch_json(_ALL_INDICES)
        if not isinstance(data, dict):
            return {}
        rows = data.get("data") or []
        for row in rows:
            name = str(row.get("index") or row.get("indexName") or "")
            if name.upper().replace(" ", "") == "INDIAVIX":
                last = row.get("last") or row.get("lastPrice")
                if last is None:
                    continue
                out = {"vix_level": float(last)}
                await self.cache.set(cache_key, json.dumps(out), _TTL_VIX)
                return out
        return {}

    # ----------------------------------------------------------- FII / DII
    async def get_fii_dii_flows(self) -> dict[str, Any]:
        cache_key = "nse:fii_dii"
        cached = await self.cache.get(cache_key)
        if cached:
            return json.loads(cached)
        data = await self._fetch_json(_FII_DII)
        if not isinstance(data, list) or not data:
            return {}
        # Each row: {"category": "FII/FPI*"|"DII**", "buyValue": "...",
        #            "sellValue": "...", "netValue": "..."}
        out: dict[str, Any] = {}
        for row in data:
            cat = str(row.get("category") or "").upper()
            try:
                net = float(row.get("netValue") or 0.0)
            except (TypeError, ValueError):
                continue
            if "FII" in cat or "FPI" in cat:
                out["fii_net_crore"] = net
            elif "DII" in cat:
                out["dii_net_crore"] = net
        if out:
            await self.cache.set(cache_key, json.dumps(out), _TTL_FII_DII)
        return out

    # --------------------------------------------------------------- PCR
    async def get_option_chain_pcr(self, symbol: str) -> dict[str, Any]:
        bare = symbol.split(".")[0].upper()
        cache_key = f"nse:pcr:{bare}"
        cached = await self.cache.get(cache_key)
        if cached:
            return json.loads(cached)
        data = await self._fetch_json(_OPTION_CHAIN, params={"symbol": bare})
        if not isinstance(data, dict):
            return {}
        records = (data.get("records") or {}).get("data") or []
        call_oi = 0.0
        put_oi = 0.0
        for r in records:
            ce = r.get("CE") or {}
            pe = r.get("PE") or {}
            try:
                call_oi += float(ce.get("openInterest") or 0)
                put_oi += float(pe.get("openInterest") or 0)
            except (TypeError, ValueError):
                continue
        if call_oi <= 0:
            return {}
        pcr = put_oi / call_oi
        if pcr > 1.2:
            signal = "bullish"
        elif pcr < 0.8:
            signal = "bearish"
        else:
            signal = "neutral"
        out = {"pcr": pcr, "pcr_signal": signal}
        await self.cache.set(cache_key, json.dumps(out), _TTL_PCR)
        return out

    # -------------------------------------------------------- Nifty trend
    async def get_nifty_trend(self, sma_50: float | None = None) -> dict[str, Any]:
        """Combine NSE allIndices snapshot with an externally-supplied 50-day
        SMA to classify NIFTY 50 as uptrend / downtrend / sideways.

        ``sma_50`` is computed by the caller from 50 daily candles via the
        Upstox provider (NSE does not publish historical candles via this
        endpoint). If ``sma_50`` is not supplied, only the spot level and
        intraday change are returned.
        """
        cache_key = "nse:nifty_snapshot"
        cached = await self.cache.get(cache_key)
        if cached:
            snapshot = json.loads(cached)
        else:
            data = await self._fetch_json(_ALL_INDICES)
            snapshot = {}
            if isinstance(data, dict):
                for row in data.get("data") or []:
                    name = str(row.get("index") or row.get("indexName") or "")
                    if name.upper().replace(" ", "") == "NIFTY50":
                        try:
                            snapshot = {
                                "nifty_level": float(row.get("last") or row.get("lastPrice") or 0),
                                "nifty_change_pct": float(row.get("percentChange") or 0.0),
                            }
                        except (TypeError, ValueError):
                            snapshot = {}
                        break
            if snapshot:
                await self.cache.set(cache_key, json.dumps(snapshot), _TTL_INDICES)

        if not snapshot:
            return {}

        out = dict(snapshot)
        if sma_50 is not None and snapshot.get("nifty_level"):
            level = snapshot["nifty_level"]
            # >1% above SMA = up; >1% below = down; otherwise sideways.
            spread = (level - sma_50) / sma_50 * 100.0 if sma_50 else 0.0
            if spread > 1.0:
                out["nifty_trend"] = "uptrend"
            elif spread < -1.0:
                out["nifty_trend"] = "downtrend"
            else:
                out["nifty_trend"] = "sideways"
        return out


__all__ = ["NSEProvider"]

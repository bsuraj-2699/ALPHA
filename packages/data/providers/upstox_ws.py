"""Upstox MarketDataFeed v3 WebSocket adapter.

Upstox's live tick feed is a binary WebSocket: the client first GETs an
authorized WebSocket URL from ``/feed/market-data-feed/authorize``, opens
that URL, then sends a JSON subscription message. Server frames arrive as
length-prefixed protobuf payloads encoded with ``MarketDataFeedV3.proto``.

This adapter exposes ``UpstoxFeed.subscribe(symbols)`` which yields
``QuoteTick`` records as new ticks arrive. Symbol → instrument-key
translation reuses ``upstox.symbol_to_instrument_key``.

The ``MarketDataFeedV3_pb2`` module is generated from Upstox's published
proto file (see https://upstox.com/developer/api-documentation/example-code/websocket).
We import it lazily so the rest of the package stays importable when the
generated stub is not yet vendored.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator

import httpx

from packages.data.providers.cache import RedisCache
from packages.data.providers.upstox import symbol_to_instrument_key

logger = logging.getLogger(__name__)

_AUTHORIZE_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

# Retrigger thresholds — see TickRetriggerEvaluator. Hoisted so the API-side
# subscriber can import the same constants when documenting behaviour.
RETRIGGER_PRICE_PCT = 0.5
RETRIGGER_VOLUME_MULTIPLIER = 2.0
RETRIGGER_FALLBACK_SECONDS = 300.0
RETRIGGER_VOLUME_WINDOW = 20
RETRIGGER_CHANNEL_PREFIX = "retrigger:"


@dataclass(frozen=True)
class QuoteTick:
    symbol: str
    ltp: float
    volume: int | None
    timestamp: datetime


@dataclass
class _SymbolState:
    last_eval_price: float | None = None
    last_eval_monotonic: float = 0.0
    volumes: deque[int] = field(default_factory=lambda: deque(maxlen=RETRIGGER_VOLUME_WINDOW))


class TickRetriggerEvaluator:
    """Decides whether a fresh tick should fire a re-evaluation.

    Two trigger paths:

      * **Event-driven** — price moved more than ``RETRIGGER_PRICE_PCT``
        since the last evaluated tick, or volume on this tick exceeded
        ``RETRIGGER_VOLUME_MULTIPLIER`` * the rolling 20-bar average.
      * **Time fallback** — at least ``RETRIGGER_FALLBACK_SECONDS`` have
        passed since the last evaluation, regardless of price action.

    State is per-symbol and lives in-process; the evaluator is intentionally
    not a coroutine — it's pure logic so the caller can publish however they
    like (Redis pub/sub, in-memory queue, test spy).
    """

    def __init__(
        self,
        *,
        price_pct: float = RETRIGGER_PRICE_PCT,
        volume_multiplier: float = RETRIGGER_VOLUME_MULTIPLIER,
        fallback_seconds: float = RETRIGGER_FALLBACK_SECONDS,
    ) -> None:
        self.price_pct = price_pct
        self.volume_multiplier = volume_multiplier
        self.fallback_seconds = fallback_seconds
        self._state: dict[str, _SymbolState] = {}

    def evaluate(self, tick: QuoteTick, *, now: float | None = None) -> dict[str, Any] | None:
        """Return a publish-ready payload if this tick should retrigger, else ``None``.

        The volume window is updated on every tick so the rolling average
        is accurate even when the tick itself didn't fire a trigger.
        """
        state = self._state.setdefault(tick.symbol, _SymbolState())
        now_mono = time.monotonic() if now is None else now

        rolling_avg = (sum(state.volumes) / len(state.volumes)) if state.volumes else 0.0
        if tick.volume is not None:
            state.volumes.append(int(tick.volume))

        # First tick we've ever seen — establish the baseline so subsequent
        # ticks can compare against something. Don't fire a retrigger off
        # the very first quote (we have no reference for "moved by 0.5%").
        if state.last_eval_price is None:
            state.last_eval_price = tick.ltp
            state.last_eval_monotonic = now_mono
            return None

        price_change_pct = (
            abs(tick.ltp - state.last_eval_price) / state.last_eval_price * 100.0
            if state.last_eval_price
            else 0.0
        )
        volume_spike = (
            tick.volume is not None
            and rolling_avg > 0
            and tick.volume > self.volume_multiplier * rolling_avg
        )
        time_since = now_mono - state.last_eval_monotonic

        reason: str | None = None
        if price_change_pct > self.price_pct:
            reason = "price_move"
        elif volume_spike:
            reason = "volume_spike"
        elif time_since >= self.fallback_seconds:
            reason = "schedule"
        if reason is None:
            return None

        payload = {
            "symbol": tick.symbol,
            "ltp": tick.ltp,
            "last_eval_price": state.last_eval_price,
            "price_change_pct": round(price_change_pct, 4),
            "volume": tick.volume,
            "rolling_avg_volume": round(rolling_avg, 2) if rolling_avg else 0.0,
            "volume_spike": volume_spike,
            "time_since_last_eval_s": round(time_since, 2),
            "reason": reason,
            "ts": tick.timestamp.isoformat(),
        }
        state.last_eval_price = tick.ltp
        state.last_eval_monotonic = now_mono
        return payload


class UpstoxFeed:
    """Async iterator over live ticks for a list of NSE symbols."""

    def __init__(self, cache: RedisCache | None = None) -> None:
        self.cache = cache if cache is not None else RedisCache()

    async def _access_token(self) -> str:
        token = await self.cache.get("upstox:access_token")
        if token:
            return token
        env_token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if env_token:
            return env_token
        raise RuntimeError("No Upstox access token available for WebSocket")

    async def _authorize(self) -> str:
        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(_AUTHORIZE_URL, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        ws_url = (body.get("data") or {}).get("authorized_redirect_uri")
        if not ws_url:
            raise RuntimeError(f"Upstox WS authorize returned no URL: {body}")
        return ws_url

    async def subscribe(self, symbols: list[str]) -> AsyncIterator[QuoteTick]:
        """Yield ``QuoteTick`` objects as ticks arrive for ``symbols``.

        The connection is held open for the lifetime of the iterator;
        consumers should ``async for`` and break out when done.
        """
        try:
            import websockets
        except ImportError as e:
            raise RuntimeError("websockets package required for UpstoxFeed") from e
        try:
            from packages.data.providers import MarketDataFeedV3_pb2 as pb  # type: ignore[attr-defined]
        except ImportError:
            pb = None
            logger.warning(
                "MarketDataFeedV3_pb2 not vendored — falling back to JSON decode "
                "(some fields may be missing)"
            )

        instrument_keys = [symbol_to_instrument_key(s) for s in symbols]
        # Map instrument_key → user-supplied symbol for emit-time labeling.
        sym_by_key = dict(zip(instrument_keys, symbols, strict=False))

        ws_url = await self._authorize()
        async with websockets.connect(ws_url) as ws:
            sub_msg = {
                "guid": "fin-agent",
                "method": "sub",
                "data": {"mode": "ltpc", "instrumentKeys": instrument_keys},
            }
            await ws.send(json.dumps(sub_msg).encode("utf-8"))

            async for raw in ws:
                if isinstance(raw, str):
                    # control / heartbeat frame
                    continue
                ticks = list(_decode_frame(raw, pb, sym_by_key))
                for tick in ticks:
                    yield tick

    async def run_retrigger_loop(
        self,
        symbols: list[str],
        redis_client: Any,
        *,
        evaluator: TickRetriggerEvaluator | None = None,
        channel_prefix: str = RETRIGGER_CHANNEL_PREFIX,
    ) -> None:
        """Subscribe to ``symbols`` and publish ``retrigger:{symbol}`` events.

        Combines :meth:`subscribe` with :class:`TickRetriggerEvaluator` so
        callers get an event-driven re-eval channel for free. ``redis_client``
        must implement an async ``publish(channel, payload)`` — typically
        ``redis.asyncio.Redis``. The coroutine runs until the underlying
        WebSocket closes or the task is cancelled.
        """
        evaluator = evaluator or TickRetriggerEvaluator()
        async for tick in self.subscribe(symbols):
            payload = evaluator.evaluate(tick)
            if payload is None:
                continue
            channel = f"{channel_prefix}{tick.symbol}"
            try:
                await redis_client.publish(channel, json.dumps(payload))
            except Exception as e:  # pragma: no cover - depends on redis
                logger.warning("retrigger publish to %s failed: %s", channel, e)


def _decode_frame(payload: bytes, pb: object | None, sym_by_key: dict[str, str]):
    """Decode one binary frame into zero or more ``QuoteTick``s.

    Uses the generated protobuf module when available; otherwise yields
    nothing — JSON-only fallback is intentionally narrow because the v3
    feed is binary-only on the wire.
    """
    if pb is None:
        return
    try:
        feed = pb.FeedResponse()  # type: ignore[attr-defined]
        feed.ParseFromString(payload)
    except Exception as e:  # pragma: no cover - depends on vendored pb
        logger.debug("upstox feed decode failed: %s", e)
        return

    feeds = getattr(feed, "feeds", None) or {}
    now = datetime.now(UTC)
    for instrument_key, msg in feeds.items():
        ltpc = getattr(msg, "ltpc", None)
        if ltpc is None:
            continue
        ltp = float(getattr(ltpc, "ltp", 0.0))
        vol_attr = getattr(ltpc, "ltq", None)
        volume = int(vol_attr) if vol_attr is not None else None
        yield QuoteTick(
            symbol=sym_by_key.get(instrument_key, instrument_key),
            ltp=ltp,
            volume=volume,
            timestamp=now,
        )


__all__ = [
    "QuoteTick",
    "RETRIGGER_CHANNEL_PREFIX",
    "RETRIGGER_FALLBACK_SECONDS",
    "RETRIGGER_PRICE_PCT",
    "RETRIGGER_VOLUME_MULTIPLIER",
    "TickRetriggerEvaluator",
    "UpstoxFeed",
]


# Silence unused-import warning when the protobuf stub is missing at lint time.
_ = asyncio

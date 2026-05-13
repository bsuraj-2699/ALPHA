"""Idempotency cache for ``POST /api/analyze``.

Key formula (``short_term`` / ``long_term``): ``sha256("{ticker}:{market}:{mode}:{YYYY-MM-DD}")[:16]``.

The same (ticker, market, **mode**) within the same UTC day maps to one
``run_id``. ``portfolio_context`` is intentionally NOT part of the key.

``intraday`` requests **do not** use this cache (see :mod:`apps.api.routes.analyze`)
so each manual intraday analysis runs the graph and can persist new rows.

Why hash and truncate? It gives us a stable, opaque, URL-safe id that
also doubles nicely as the LangGraph thread_id. 16 hex chars = 64 bits of
keyspace, enough for the volume we expect.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


def make_idempotency_key(
    ticker: str,
    market: str,
    *,
    mode: str = "long_term",
    now: datetime | None = None,
) -> str:
    """Compute the deterministic key for a request.

    Parameters
    ----------
    ticker, market
        Pre-validated request fields. Caller has already normalized ticker
        to upper-case via the request model's validator.
    mode
        Run horizon; included so a long-term run does not dedupe an intraday
        run for the same name on the same day.
    now
        Override the wall-clock for testing. Defaults to ``datetime.now(UTC)``.
    """
    now = now or datetime.now(timezone.utc)
    raw = f"{ticker}:{market}:{mode}:{now.strftime('%Y-%m-%d')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class IdempotencyCache(Protocol):
    """Maps idempotency_key -> run_id with a TTL."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, run_id: str, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


class InMemoryIdempotencyCache:
    def __init__(self) -> None:
        # key -> (run_id, expiry_ts)
        self._store: dict[str, tuple[str, datetime]] = {}

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        run_id, expires_at = entry
        if datetime.now(timezone.utc) >= expires_at:
            self._store.pop(key, None)
            return None
        return run_id

    async def set(self, key: str, run_id: str, ttl_seconds: int) -> None:
        from datetime import timedelta

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self._store[key] = (run_id, expires_at)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Redis implementation
# ---------------------------------------------------------------------------


class RedisIdempotencyCache:
    KEY_PREFIX = "idempotency:"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    @classmethod
    def from_url(cls, url: str) -> "RedisIdempotencyCache":
        import redis.asyncio as redis_async

        client = redis_async.from_url(url, decode_responses=True)
        return cls(client)

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(f"{self.KEY_PREFIX}{key}")
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def set(self, key: str, run_id: str, ttl_seconds: int) -> None:
        await self._redis.set(
            f"{self.KEY_PREFIX}{key}", run_id, ex=ttl_seconds
        )

    async def delete(self, key: str) -> None:
        await self._redis.delete(f"{self.KEY_PREFIX}{key}")


__all__ = [
    "IdempotencyCache",
    "InMemoryIdempotencyCache",
    "RedisIdempotencyCache",
    "make_idempotency_key",
]

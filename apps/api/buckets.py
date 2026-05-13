"""Strategy-bucket persistence.

The Runs page lets the user enroll up to five tickers per strategy
mode (``intraday`` / ``short_term`` / ``long_term``). The frontend
stores the same lists in browser localStorage so the UI is responsive
offline, but the *scheduler* needs to know what to schedule even when
no browser is open — so we mirror the buckets server-side.

Two adapters share the protocol:

  * :class:`InMemoryBucketStore` — process-local dict, used when Redis
    isn't configured (tests, local dev).
  * :class:`RedisBucketStore` — Redis hash per mode, survives restarts
    and is read by ``apps/api/scheduler.py`` on every tick.

Tickers are kept in display form (no ``.NS`` suffix) — every consumer
on the server side already routes through
:func:`packages.shared.ticker_registry.to_upstox` (or equivalent) when
it actually needs the provider key, so storing the bare symbol keeps
the cache human-readable and matches what the frontend persists.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)


# Match the literal type used in `apps/api/models.py` and
# `apps/web/lib/strategy.ts`. Kept as a plain tuple so callers can use
# ``in BUCKET_MODES`` without importing typing.Literal.
BUCKET_MODES: tuple[str, ...] = ("intraday", "short_term", "long_term")
MAX_BUCKET_SIZE = 5

_REDIS_KEY_PREFIX = "fin-agent:buckets"


def _normalize(ticker: str) -> str:
    """Display form: uppercase, strip ``.NS``/``.BO`` and whitespace."""
    out = ticker.strip().upper()
    if out.endswith((".NS", ".BO")):
        out = out.rsplit(".", 1)[0]
    return out


def _dedupe_keep_order(seq: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in seq:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


class BucketStore(Protocol):
    """Async surface every bucket adapter implements."""

    async def list(self, mode: str) -> list[str]: ...
    async def add(self, mode: str, tickers: list[str]) -> list[str]: ...
    async def remove(self, mode: str, ticker: str) -> list[str]: ...
    async def replace(self, mode: str, tickers: list[str]) -> list[str]: ...
    async def all(self) -> dict[str, list[str]]: ...
    async def close(self) -> None: ...


class InMemoryBucketStore:
    """Plain dict-backed store. Lives only as long as the process."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[str]] = {m: [] for m in BUCKET_MODES}

    async def list(self, mode: str) -> list[str]:
        self._guard_mode(mode)
        return list(self._buckets[mode])

    async def add(self, mode: str, tickers: list[str]) -> list[str]:
        self._guard_mode(mode)
        normalized = [_normalize(t) for t in tickers if t]
        merged = _dedupe_keep_order(self._buckets[mode] + normalized)
        self._buckets[mode] = merged[:MAX_BUCKET_SIZE]
        return list(self._buckets[mode])

    async def remove(self, mode: str, ticker: str) -> list[str]:
        self._guard_mode(mode)
        target = _normalize(ticker)
        self._buckets[mode] = [t for t in self._buckets[mode] if t != target]
        return list(self._buckets[mode])

    async def replace(self, mode: str, tickers: list[str]) -> list[str]:
        self._guard_mode(mode)
        normalized = _dedupe_keep_order(_normalize(t) for t in tickers if t)
        self._buckets[mode] = normalized[:MAX_BUCKET_SIZE]
        return list(self._buckets[mode])

    async def all(self) -> dict[str, list[str]]:
        return {m: list(v) for m, v in self._buckets.items()}

    async def close(self) -> None:
        return None

    @staticmethod
    def _guard_mode(mode: str) -> None:
        if mode not in BUCKET_MODES:
            raise ValueError(
                f"Unknown bucket mode {mode!r}; expected one of {BUCKET_MODES}"
            )


class RedisBucketStore:
    """Redis-backed store (one key per mode storing a JSON array).

    The key shape is ``fin-agent:buckets:{mode}``. Using a key per mode
    keeps GET / SET atomic for the whole bucket which is what the
    scheduler wants — it pulls one list at a time on each tick.
    """

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    @classmethod
    def from_url(cls, url: str) -> "RedisBucketStore":
        import redis.asyncio as redis_async

        client = redis_async.from_url(url, decode_responses=True)
        return cls(client)

    @staticmethod
    def _key(mode: str) -> str:
        return f"{_REDIS_KEY_PREFIX}:{mode}"

    async def list(self, mode: str) -> list[str]:
        InMemoryBucketStore._guard_mode(mode)
        raw = await self._redis.get(self._key(mode))
        return _decode(raw)

    async def add(self, mode: str, tickers: list[str]) -> list[str]:
        InMemoryBucketStore._guard_mode(mode)
        cur = await self.list(mode)
        normalized = [_normalize(t) for t in tickers if t]
        merged = _dedupe_keep_order(cur + normalized)[:MAX_BUCKET_SIZE]
        await self._redis.set(self._key(mode), json.dumps(merged))
        return merged

    async def remove(self, mode: str, ticker: str) -> list[str]:
        InMemoryBucketStore._guard_mode(mode)
        cur = await self.list(mode)
        target = _normalize(ticker)
        next_list = [t for t in cur if t != target]
        await self._redis.set(self._key(mode), json.dumps(next_list))
        return next_list

    async def replace(self, mode: str, tickers: list[str]) -> list[str]:
        InMemoryBucketStore._guard_mode(mode)
        normalized = _dedupe_keep_order(
            _normalize(t) for t in tickers if t
        )[:MAX_BUCKET_SIZE]
        await self._redis.set(self._key(mode), json.dumps(normalized))
        return normalized

    async def all(self) -> dict[str, list[str]]:
        keys = [self._key(m) for m in BUCKET_MODES]
        raw_values = await self._redis.mget(keys)
        return {
            mode: _decode(raw)
            for mode, raw in zip(BUCKET_MODES, raw_values)
        }

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except Exception:  # pragma: no cover
            pass


def _decode(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [_normalize(str(x)) for x in data if x]


__all__ = [
    "BUCKET_MODES",
    "BucketStore",
    "InMemoryBucketStore",
    "MAX_BUCKET_SIZE",
    "RedisBucketStore",
]

"""Per-run event bus + SSE adapter.

The bus has two responsibilities:

  1. Receive events emitted by the orchestrator (via
     :func:`packages.shared.observability.publish_event` propagated through
     a ContextVar).
  2. Hand those events to SSE consumers subscribed to a particular run.

Two implementations are provided:

  * :class:`InMemoryEventBus` - asyncio queues per run. Default; used by
    tests and single-process deployments.
  * :class:`RedisEventBus` - Redis pub/sub. Used when ``REDIS_URL`` is
    configured so the API can be horizontally scaled without sticky
    sessions.

Both expose the same surface: ``publish``, ``subscribe`` (an async
generator yielding events until a terminal one), and ``close``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# Terminal event types: the SSE generator closes once any of these fire.
# `_terminal_` is an internal marker the RunManager publishes to ensure
# subscribers always get a definitive end-of-stream, even on early exit.
TERMINAL_EVENT_TYPES = frozenset({"decision", "error", "interrupted", "_terminal_"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus(Protocol):
    async def publish(
        self, run_id: str, event_type: str, data: dict[str, Any]
    ) -> None: ...

    def subscribe(self, run_id: str) -> AsyncIterator[dict[str, Any]]: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


class InMemoryEventBus:
    """asyncio-queue-per-subscriber bus.

    Multiple subscribers per run are supported (each gets their own queue).
    Events published before any subscriber connects are NOT replayed —
    consumers that arrive late should fetch the terminal state via
    ``GET /api/runs/{run_id}`` instead.
    """

    def __init__(self) -> None:
        # run_id -> set of queues, one per subscriber
        self._queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(
        self, run_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        envelope = {
            "type": event_type,
            "data": data,
            "ts": _now_iso(),
        }
        async with self._lock:
            queues = list(self._queues.get(run_id, ()))
        for q in queues:
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:  # pragma: no cover
                logger.warning("event queue full for run %s; dropping event", run_id)

    async def subscribe(  # type: ignore[override]
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1024)
        async with self._lock:
            self._queues[run_id].add(q)
        try:
            while True:
                event = await q.get()
                yield event
                if event["type"] in TERMINAL_EVENT_TYPES:
                    break
        finally:
            async with self._lock:
                self._queues.get(run_id, set()).discard(q)
                if not self._queues.get(run_id):
                    self._queues.pop(run_id, None)

    async def ping(self) -> None:
        return

    async def close(self) -> None:
        async with self._lock:
            self._queues.clear()


# ---------------------------------------------------------------------------
# Redis implementation
# ---------------------------------------------------------------------------


class RedisEventBus:
    """Redis pub/sub bus.

    Channel naming: ``run:{run_id}`` (one channel per run). Events are
    JSON-encoded envelopes identical to the in-memory format.
    """

    CHANNEL_PREFIX = "run:"

    def __init__(self, redis_client: Any) -> None:
        # redis is redis.asyncio.Redis; typed as Any to avoid forcing the
        # dependency on every importer.
        self._redis = redis_client

    @classmethod
    def from_url(cls, url: str) -> "RedisEventBus":
        import redis.asyncio as redis_async

        client = redis_async.from_url(url, decode_responses=True)
        return cls(client)

    async def publish(
        self, run_id: str, event_type: str, data: dict[str, Any]
    ) -> None:
        envelope = {"type": event_type, "data": data, "ts": _now_iso()}
        await self._redis.publish(
            f"{self.CHANNEL_PREFIX}{run_id}", json.dumps(envelope)
        )

    async def subscribe(  # type: ignore[override]
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        channel = f"{self.CHANNEL_PREFIX}{run_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    event = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                yield event
                if event.get("type") in TERMINAL_EVENT_TYPES:
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    async def ping(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        try:
            await self._redis.aclose()
        except AttributeError:  # pragma: no cover - older redis-py
            await self._redis.close()


__all__ = [
    "EventBus",
    "InMemoryEventBus",
    "RedisEventBus",
    "TERMINAL_EVENT_TYPES",
]

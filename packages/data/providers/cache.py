"""Tiny Redis-backed JSON cache used by every provider.

Degrades to no-op if `REDIS_URL` is unset or the server is unreachable, so unit
tests and offline development still work.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class RedisCache:
    """Thin wrapper around redis.asyncio with a get/set/json contract.

    The actual `redis` import is deferred so the providers package stays
    importable without the dependency installed.
    """

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.getenv("REDIS_URL")
        self._client: Any | None = None
        self._unavailable = False

    async def _get_client(self) -> Any | None:
        if self._unavailable or not self.url:
            return None
        if self._client is not None:
            return self._client
        try:
            from redis.asyncio import from_url
        except ImportError:
            logger.debug("redis package not installed — cache disabled")
            self._unavailable = True
            return None
        try:
            client = from_url(self.url, decode_responses=True)
            await client.ping()
        except Exception as e:
            logger.debug("redis unreachable (%s) — cache disabled", e)
            self._unavailable = True
            return None
        self._client = client
        return client

    async def get(self, key: str) -> str | None:
        client = await self._get_client()
        if client is None:
            return None
        try:
            return await client.get(key)
        except Exception as e:
            logger.debug("redis GET %s failed: %s", key, e)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.set(key, value, ex=ttl_seconds)
        except Exception as e:
            logger.debug("redis SET %s failed: %s", key, e)

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

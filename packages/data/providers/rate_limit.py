"""Async token-bucket rate limiter shared by every provider."""

from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Coroutine-safe token bucket.

    `rate` is tokens added per second; `capacity` is the max burst (defaults to
    `rate`, so the bucket allows one second of traffic up-front).

    Usage:
        limiter = RateLimiter.per_minute(60)
        async with limiter:
            await fetch()

    or explicitly:
        await limiter.acquire()
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = float(capacity) if capacity is not None else float(rate)
        self._tokens = self.capacity
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    @classmethod
    def per_minute(cls, n: float) -> RateLimiter:
        return cls(rate=n / 60.0, capacity=n)

    @classmethod
    def per_second(cls, n: float) -> RateLimiter:
        return cls(rate=n, capacity=n)

    async def acquire(self, tokens: float = 1.0) -> None:
        if tokens > self.capacity:
            raise ValueError(f"requested {tokens} tokens > capacity {self.capacity}")
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / self.rate
                await asyncio.sleep(wait)

    async def __aenter__(self) -> RateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

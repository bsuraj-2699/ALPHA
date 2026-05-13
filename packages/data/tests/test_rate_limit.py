"""Unit tests for RateLimiter — pure asyncio, no external deps."""

from __future__ import annotations

import asyncio
import time

import pytest

from packages.data.providers.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_burst_within_capacity_is_immediate():
    limiter = RateLimiter(rate=10, capacity=5)
    start = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed < 0.05, f"5 tokens within capacity should be ~instant, was {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_overflow_waits_for_refill():
    limiter = RateLimiter(rate=20, capacity=2)  # 50ms per token after burst
    start = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    # 2 instant + 2 paced at 50ms each = ~100ms
    assert 0.08 < elapsed < 0.25, f"expected ~0.1s, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_per_minute_factory():
    limiter = RateLimiter.per_minute(60)
    assert limiter.rate == pytest.approx(1.0)
    assert limiter.capacity == 60


@pytest.mark.asyncio
async def test_invalid_rate():
    with pytest.raises(ValueError):
        RateLimiter(rate=0)
    with pytest.raises(ValueError):
        RateLimiter(rate=-1)


@pytest.mark.asyncio
async def test_concurrent_acquires_serialized():
    limiter = RateLimiter(rate=10, capacity=2)

    async def call() -> float:
        await limiter.acquire()
        return time.monotonic()

    start = time.monotonic()
    timings = await asyncio.gather(*[call() for _ in range(6)])
    elapsed = max(timings) - start
    # Burst of 2, then 4 more at 100ms each → ~0.4s
    assert elapsed > 0.3

"""Rate limiter + guardrail unit tests."""

from __future__ import annotations

import asyncio
import time

import pydantic
from packages.agents.guardrails import (
    AsyncRateLimiter,
    apply_input_guardrails,
    apply_output_guardrails,
)


async def test_rate_limiter_bounds_requests_per_minute():
    # 2 requests/min already spent: the next acquire must wait for the window.
    limiter = AsyncRateLimiter(max_per_minute=2, max_concurrency=10)
    now = time.monotonic()
    limiter._events.extend([now, now])

    done = asyncio.Event()

    async def _run() -> None:
        async with limiter:
            done.set()

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.05)
    assert not done.is_set()  # blocked by the RPM window
    task.cancel()


async def test_rate_limiter_concurrency_semaphore():
    limiter = AsyncRateLimiter(max_per_minute=1000, max_concurrency=1)
    order: list[str] = []

    async def _work(tag: str) -> None:
        async with limiter:
            order.append(f"enter-{tag}")
            await asyncio.sleep(0.02)
            order.append(f"exit-{tag}")

    await asyncio.gather(_work("a"), _work("b"))
    # Serialised: one fully completes before the other enters.
    assert order in (
        ["enter-a", "exit-a", "enter-b", "exit-b"],
        ["enter-b", "exit-b", "enter-a", "exit-a"],
    )


def test_input_guardrails_truncate_long_prompt():
    messages = [{"role": "user", "content": "y" * 100}]
    out = apply_input_guardrails(messages, max_prompt_chars=10)
    assert len(out[0]["content"]) == 10


def test_output_guardrails_clamp_and_strip():
    class _N(pydantic.BaseModel):
        narrative: str
        top_signals: list[str]
        confidence: float

    result = _N(
        narrative="ok\x00bad" + "z" * 100,
        top_signals=["clean", "dir\x01ty"],
        confidence=5.0,
    )
    out = apply_output_guardrails(result, max_output_chars=20)
    assert "\x00" not in out.narrative
    assert len(out.narrative) <= 20
    assert "\x01" not in out.top_signals[1]
    assert out.confidence == 1.0


def test_output_guardrails_noop_on_non_model():
    assert apply_output_guardrails("plain", max_output_chars=5) == "plain"

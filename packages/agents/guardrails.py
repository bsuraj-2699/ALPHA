"""Guardrails and rate limiting for agent LLM usage.

Two independent protections wrap every structured narration call:

* :class:`AsyncRateLimiter` — a process-global limiter bounding both the
  requests-per-minute and the number of concurrent in-flight calls to the
  model provider, so a burst of runs cannot exhaust a hosted quota.
* input / output guardrails — cap prompt size before sending, and sanitise the
  model's structured output afterwards (truncate over-long prose, clamp the
  confidence axis into ``[0, 1]``, strip control characters). These never touch
  signal / score / size — those come only from the deterministic engine.

All limits are env-configured with production-safe defaults.
"""

from __future__ import annotations

import asyncio
import os
import time
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import Any


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class GuardrailConfig:
    max_requests_per_minute: int = 60
    max_concurrency: int = 4
    max_prompt_chars: int = 24_000
    max_output_chars: int = 4_000

    @classmethod
    def from_env(cls) -> GuardrailConfig:
        return cls(
            max_requests_per_minute=_env_int("LLM_MAX_REQUESTS_PER_MINUTE", 60),
            max_concurrency=_env_int("LLM_MAX_CONCURRENCY", 4),
            max_prompt_chars=_env_int("LLM_MAX_PROMPT_CHARS", 24_000),
            max_output_chars=_env_int("LLM_MAX_OUTPUT_CHARS", 4_000),
        )


class AsyncRateLimiter:
    """Sliding-window RPM limiter combined with a concurrency semaphore."""

    def __init__(self, max_per_minute: int, max_concurrency: int) -> None:
        self._max_per_minute = max(1, max_per_minute)
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def _await_slot(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0] >= 60.0:
                    self._events.popleft()
                if len(self._events) < self._max_per_minute:
                    self._events.append(now)
                    return
                wait = 60.0 - (now - self._events[0])
            await asyncio.sleep(max(wait, 0.01))

    async def __aenter__(self) -> AsyncRateLimiter:
        await self._semaphore.acquire()
        try:
            await self._await_slot()
        except BaseException:
            self._semaphore.release()
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self._semaphore.release()


_config: GuardrailConfig | None = None
_limiter: AsyncRateLimiter | None = None


def get_config() -> GuardrailConfig:
    global _config
    if _config is None:
        _config = GuardrailConfig.from_env()
    return _config


def get_rate_limiter() -> AsyncRateLimiter:
    global _limiter
    if _limiter is None:
        cfg = get_config()
        _limiter = AsyncRateLimiter(cfg.max_requests_per_minute, cfg.max_concurrency)
    return _limiter


def reset() -> None:
    """Drop cached config / limiter so new env values take effect (tests)."""
    global _config, _limiter
    _config = None
    _limiter = None


def apply_input_guardrails(
    messages: list[dict[str, str]], max_prompt_chars: int
) -> list[dict[str, str]]:
    """Truncate any single message content that exceeds the prompt-size cap."""
    guarded: list[dict[str, str]] = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > max_prompt_chars:
            content = content[:max_prompt_chars]
        guarded.append({**msg, "content": content})
    return guarded


def _clean_text(text: str, max_chars: int) -> str:
    stripped = "".join(
        ch for ch in text if ch == "\n" or unicodedata.category(ch)[0] != "C"
    )
    if len(stripped) > max_chars:
        stripped = stripped[:max_chars].rstrip()
    return stripped


def apply_output_guardrails(result: Any, max_output_chars: int) -> Any:
    """Sanitise a structured narration result.

    Truncates string fields, strips control characters, and clamps any field
    named ``confidence`` into ``[0, 1]``. Works on Pydantic models (returns a
    validated copy) and is a no-op for anything else.
    """
    fields = getattr(type(result), "model_fields", None)
    if not fields:
        return result

    updates: dict[str, Any] = {}
    for name in fields:
        value = getattr(result, name, None)
        if name == "confidence" and isinstance(value, (int, float)):
            clamped = min(1.0, max(0.0, float(value)))
            if clamped != value:
                updates[name] = clamped
        elif isinstance(value, str):
            cleaned = _clean_text(value, max_output_chars)
            if cleaned != value:
                updates[name] = cleaned
        elif isinstance(value, list):
            cleaned_list = [
                _clean_text(v, max_output_chars) if isinstance(v, str) else v
                for v in value
            ]
            if cleaned_list != value:
                updates[name] = cleaned_list

    if not updates:
        return result
    try:
        return result.model_copy(update=updates)
    except Exception:
        return result


__all__ = [
    "AsyncRateLimiter",
    "GuardrailConfig",
    "apply_input_guardrails",
    "apply_output_guardrails",
    "get_config",
    "get_rate_limiter",
    "reset",
]

"""Model Provider Layer.

A single, config-driven seam for structured LLM calls. Agents depend on the
``ChatProvider`` interface only — no agent imports ``litellm``, ``instructor``,
or any vendor SDK, and no agent hardcodes a model id. The whole system talks to
ONE OpenAI-compatible provider (default: NVIDIA NIM) serving open-weight models,
with a primary model and a genuine fallback model that takes over on failure.

Every call flows through :class:`GuardedChatProvider`, which applies the rate
limiter and input/output guardrails, then :class:`FailoverChatProvider`, which
tries the primary model and falls back to the second on any error.

The Rule Engine and the deterministic decision path never touch this module —
models only ever write narrative prose.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from packages.agents.guardrails import (
    apply_input_guardrails,
    apply_output_guardrails,
    get_config,
    get_rate_limiter,
)
from packages.agents.llm_provider import (
    api_base,
    api_key,
    is_any_llm_configured,
    model_ids,
    request_timeout,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default reasoning/narration model for the whole system.
DEFAULT_CHAT_MODEL = "meta/llama-3.1-8b-instruct"

# Headroom added to LLM_TIMEOUT for the hard wall-clock cap on one model call,
# so the transport's own timeout wins the race in the normal case.
_WALL_CLOCK_GRACE_SECONDS = 5.0


@runtime_checkable
class ChatProvider(Protocol):
    """The only LLM surface agents are allowed to depend on."""

    name: str
    model: str

    async def complete(
        self,
        *,
        response_model: type[T],
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> T: ...


# LiteLLM routing prefixes we leave untouched; anything else (e.g. a bare
# ``meta/llama-3.3-70b-instruct`` NIM id) is sent via the OpenAI-compatible path.
_LITELLM_PREFIXES: frozenset[str] = frozenset(
    {"openai", "hosted_vllm", "ollama", "ollama_chat", "nvidia_nim"}
)


def _routed_model(model: str) -> str:
    """Route through LiteLLM's OpenAI-compatible path unless already prefixed."""
    if model.split("/", 1)[0] in _LITELLM_PREFIXES:
        return model
    return f"openai/{model}"


@dataclass
class LiteLLMChatProvider:
    """``ChatProvider`` backed by LiteLLM + instructor against one endpoint.

    This is the one place that imports the LLM SDKs. It delegates to the
    usage-tracked helper so token accounting is unchanged.
    """

    model: str
    base_url: str = field(default_factory=api_base)
    key: str = field(default_factory=api_key)
    name: str = "nim"

    async def complete(
        self,
        *,
        response_model: type[T],
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> T:
        from packages.agents._llm_helpers import openai_create_tracked
        from packages.agents.llm_provider import get_litellm_instructor_client

        client = get_litellm_instructor_client()
        timeout = request_timeout()
        # ``timeout`` bounds a single HTTP attempt; ``max_retries`` is consumed
        # by ``instructor.create`` for schema-validation retries and never
        # reaches the transport. Neither bounds the OpenAI SDK's own retries
        # (DEFAULT_MAX_RETRIES = 2), so a hung endpoint costs 3 x timeout —
        # hence the hard wall-clock cap below.
        kwargs.setdefault("timeout", timeout)
        # instructor's schema-validation retries. At 1 there are none: a single
        # malformed generation raises InstructorRetryException and burns a
        # failover. Re-prompting with the validation error is instructor's whole
        # reliability mechanism and is what small open-weight models need; the
        # cost is only paid on failure, and wait_for below still bounds it.
        kwargs.setdefault("max_retries", 3)
        return await asyncio.wait_for(
            openai_create_tracked(
                client,
                model=_routed_model(self.model),
                response_model=response_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                api_base=self.base_url,
                api_key=self.key,
                **kwargs,
            ),
            # Grace so litellm's own timeout raises first (clearer error) in
            # the normal case; we only intervene during a retry storm.
            timeout=timeout + _WALL_CLOCK_GRACE_SECONDS,
        )


@dataclass
class FailoverChatProvider:
    """Tries each model in order until one succeeds.

    Fixes the "primary down -> straight to templated" gap: if the primary model
    raises (rate limit / quota / connection error), the fallback model is
    attempted before giving up. Only when ALL models fail does ``complete``
    raise (callers then use templated prose).
    """

    providers: list[LiteLLMChatProvider]

    @property
    def name(self) -> str:
        return "failover(" + ",".join(p.model for p in self.providers) + ")"

    @property
    def model(self) -> str:
        return self.providers[0].model if self.providers else DEFAULT_CHAT_MODEL

    async def complete(
        self,
        *,
        response_model: type[T],
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> T:
        last_exc: Exception | None = None
        for p in self.providers:
            try:
                return await p.complete(
                    response_model=response_model, messages=messages,
                    max_tokens=max_tokens, temperature=temperature, **kwargs,
                )
            except Exception as e:
                last_exc = e
                logger.warning(
                    "chat model %s failed: %s; trying fallback",
                    p.model, type(e).__name__,
                )
        raise last_exc if last_exc is not None else RuntimeError(
            "no chat models configured"
        )


@dataclass
class GuardedChatProvider:
    """Wraps a provider with the rate limiter and input/output guardrails."""

    inner: ChatProvider

    @property
    def name(self) -> str:
        return f"guarded({self.inner.name})"

    @property
    def model(self) -> str:
        return self.inner.model

    async def complete(
        self,
        *,
        response_model: type[T],
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> T:
        cfg = get_config()
        guarded_messages = apply_input_guardrails(messages, cfg.max_prompt_chars)
        async with get_rate_limiter():
            result = await self.inner.complete(
                response_model=response_model, messages=guarded_messages,
                max_tokens=max_tokens, temperature=temperature, **kwargs,
            )
        return apply_output_guardrails(result, cfg.max_output_chars)


def get_chat_provider(fallback_model: str = DEFAULT_CHAT_MODEL) -> ChatProvider:
    """Return the active guarded :class:`ChatProvider` (config-driven).

    Builds the primary + fallback models over the single configured endpoint,
    wraps them in failover, then in the guardrail/rate-limit layer.
    ``fallback_model`` is used only when nothing is configured (offline).
    """
    if not is_any_llm_configured():
        return LiteLLMChatProvider(model=fallback_model, name="offline")

    providers = [LiteLLMChatProvider(model=m) for m in model_ids()]
    inner: ChatProvider = (
        providers[0] if len(providers) == 1 else FailoverChatProvider(providers)
    )
    return GuardedChatProvider(inner)


def is_configured() -> bool:
    """Whether the chat model endpoint is available."""
    return is_any_llm_configured()


__all__ = [
    "DEFAULT_CHAT_MODEL",
    "ChatProvider",
    "FailoverChatProvider",
    "GuardedChatProvider",
    "LiteLLMChatProvider",
    "get_chat_provider",
    "is_configured",
]

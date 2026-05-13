"""Resolve which LLM backend to use from available API keys.

The pipeline uses `instructor` structured outputs. Any provider supported
by LiteLLM works: we pick the first provider in ``LLM_PROVIDER_PRIORITY``
that has a non-empty API key env var.

Environment
-----------
OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY (or GOOGLE_API_KEY for
Gemini on AI Studio), MISTRAL_API_KEY, GROQ_API_KEY

Optional:

LLM_PROVIDER_PRIORITY
    Comma-separated provider ids. Default:
    ``openai,anthropic,gemini,mistral,groq``.

LLM_MODEL
    Force a LiteLLM model id for all chat calls (e.g. ``gpt-4o-mini``,
    ``anthropic/claude-3-5-sonnet-20241022``, ``gemini/gemini-2.0-flash``).

OPENAI_MODEL
    When the active provider is OpenAI and ``LLM_MODEL`` is unset, this
    selects the model (default from callers / ``gpt-4o``).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

# Env vars stripped by eval/offline helpers so templated fallbacks run.
LLM_API_KEY_ENV_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
)

_DEFAULT_PRIORITY: tuple[str, ...] = (
    "openai",
    "anthropic",
    "gemini",
    "mistral",
    "groq",
)

# LiteLLM model ids when the operator does not set LLM_MODEL.
_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o",
    "anthropic": "anthropic/claude-3-5-sonnet-20241022",
    "gemini": "gemini/gemini-2.0-flash",
    "mistral": "mistral/mistral-small-latest",
    "groq": "groq/llama-3.3-70b-versatile",
}

_PROVIDER_KEY_ENV: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
}

_instructor_client: object | None = None


def _env_nonempty(name: str) -> bool:
    v = os.getenv(name)
    return v is not None and bool(v.strip())


def _provider_has_credentials(provider: str) -> bool:
    for key in _PROVIDER_KEY_ENV.get(provider, ()):
        if _env_nonempty(key):
            return True
    return False


def _parse_priority() -> tuple[str, ...]:
    raw = os.getenv("LLM_PROVIDER_PRIORITY", "")
    if not raw.strip():
        return _DEFAULT_PRIORITY
    parts = tuple(p.strip().lower() for p in raw.split(",") if p.strip())
    if not parts:
        return _DEFAULT_PRIORITY
    unknown = [p for p in parts if p not in _PROVIDER_KEY_ENV]
    if unknown:
        # Ignore unknown tokens so a typo does not blank the whole list.
        parts = tuple(p for p in parts if p in _PROVIDER_KEY_ENV)
    return parts or _DEFAULT_PRIORITY


@dataclass(frozen=True)
class ResolvedLLM:
    """Active chat LLM (LiteLLM routing + model id)."""

    provider: str
    model: str


def resolve_llm() -> ResolvedLLM | None:
    """First provider in priority order with any configured API key."""
    for provider in _parse_priority():
        if _provider_has_credentials(provider):
            model = effective_chat_model_for_provider(provider)
            return ResolvedLLM(provider=provider, model=model)
    return None


def is_any_llm_configured() -> bool:
    return resolve_llm() is not None


def effective_chat_model_for_provider(provider: str) -> str:
    """Model id for ``provider`` respecting ``LLM_MODEL`` / ``OPENAI_MODEL``."""
    forced = os.getenv("LLM_MODEL", "").strip()
    if forced:
        return forced
    if provider == "openai":
        return os.getenv("OPENAI_MODEL", "").strip() or _DEFAULT_MODELS["openai"]
    return _DEFAULT_MODELS.get(provider, _DEFAULT_MODELS["openai"])


def effective_chat_model(openai_fallback: str) -> str:
    """Model for the currently resolved provider (or OpenAI-style fallback)."""
    forced = os.getenv("LLM_MODEL", "").strip()
    if forced:
        return forced
    resolved = resolve_llm()
    if resolved is None:
        return openai_fallback
    if resolved.provider == "openai":
        return os.getenv("OPENAI_MODEL", "").strip() or openai_fallback
    return resolved.model


def get_litellm_instructor_client() -> object:
    """Singleton ``instructor`` client backed by ``litellm.acompletion``."""
    global _instructor_client
    if _instructor_client is None:
        import instructor
        import litellm

        _instructor_client = instructor.from_litellm(litellm.acompletion)
    return _instructor_client


@contextmanager
def llm_env_stripped_offline() -> Iterator[dict[str, str | None]]:
    """Remove all known LLM API keys; restore prior values on exit.

    Returns the mapping of env name -> original value (for tests).
    """
    saved: dict[str, str | None] = {}
    for name in LLM_API_KEY_ENV_NAMES:
        saved[name] = os.environ.pop(name, None)
    try:
        yield saved
    finally:
        for name, val in saved.items():
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val


__all__ = [
    "LLM_API_KEY_ENV_NAMES",
    "ResolvedLLM",
    "effective_chat_model",
    "effective_chat_model_for_provider",
    "get_litellm_instructor_client",
    "is_any_llm_configured",
    "llm_env_stripped_offline",
    "resolve_llm",
]

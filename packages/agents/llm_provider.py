"""Resolve the single hosted LLM backend used for narration.

The system uses ONE OpenAI-compatible provider that serves open-weight models
(default: NVIDIA NIM). Two model ids are configured — a primary and a fallback —
and both are fully capable of every narration call. The provider is
OpenAI-compatible, so the same wiring works if the operator points
``LLM_API_BASE`` at any other compatible host (Groq, OpenRouter, a local
vLLM/Ollama ``/v1``).

The Rule Engine and the deterministic decision path never touch this module —
LLMs only ever write prose.

Environment
-----------
LLM_API_BASE
    OpenAI-compatible base URL. Default: NVIDIA NIM
    (``https://integrate.api.nvidia.com/v1``).
LLM_API_KEY
    API key for the endpoint. When empty the whole pipeline runs offline with
    templated prose (no external calls).
LLM_MODEL
    Primary model id. Default ``meta/llama-3.3-70b-instruct``.
LLM_FALLBACK_MODEL
    Fallback model id used when the primary call fails (quota / outage / error).
    Default ``nvidia/llama-3.1-nemotron-70b-instruct``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

# Env vars stripped by eval/offline helpers so templated fallbacks run.
LLM_API_KEY_ENV_NAMES: tuple[str, ...] = (
    "LLM_API_KEY",
    "LLM_API_BASE",
)

DEFAULT_API_BASE = "https://integrate.api.nvidia.com/v1"
# Both must support tool/function calling: instructor needs structured output,
# and most NIM catalogue models fail it (InstructorRetryException) or are not
# entitled for a given account (404 "Function ... not found"). Verified working
# on this account; re-probe before changing.
DEFAULT_PRIMARY_MODEL = "meta/llama-3.1-8b-instruct"
DEFAULT_FALLBACK_MODEL = "nvidia/nvidia-nemotron-nano-9b-v2"

_instructor_client: object | None = None


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v.strip() if v is not None and v.strip() else default


def api_base() -> str:
    return _env("LLM_API_BASE", DEFAULT_API_BASE)


def api_key() -> str:
    return _env("LLM_API_KEY")


def primary_model() -> str:
    return _env("LLM_MODEL", DEFAULT_PRIMARY_MODEL)


def fallback_model() -> str:
    return _env("LLM_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)


def request_timeout() -> float:
    """Per-call timeout (seconds). A slow/hung model then raises so the failover
    layer tries the fallback (or the caller uses templated prose)."""
    raw = _env("LLM_TIMEOUT", "25")
    try:
        val = float(raw)
    except ValueError:
        return 25.0
    return val if val > 0 else 25.0


def model_ids() -> list[str]:
    """Primary then fallback, de-duplicated, preserving order."""
    ids: list[str] = []
    for m in (primary_model(), fallback_model()):
        if m and m not in ids:
            ids.append(m)
    return ids


def is_any_llm_configured() -> bool:
    """True when an API key is present — otherwise the pipeline stays offline."""
    return bool(api_key())


def get_litellm_instructor_client() -> object:
    """Singleton ``instructor`` client backed by ``litellm.acompletion``."""
    global _instructor_client
    if _instructor_client is None:
        import instructor
        import litellm
        from packages.shared.tracing import init_tracing

        init_tracing()
        _instructor_client = instructor.from_litellm(litellm.acompletion)
    return _instructor_client


@contextmanager
def llm_env_stripped_offline() -> Iterator[dict[str, str | None]]:
    """Remove the LLM credentials; restore prior values on exit.

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
    "DEFAULT_API_BASE",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_PRIMARY_MODEL",
    "LLM_API_KEY_ENV_NAMES",
    "api_base",
    "api_key",
    "fallback_model",
    "get_litellm_instructor_client",
    "is_any_llm_configured",
    "llm_env_stripped_offline",
    "model_ids",
    "primary_model",
]

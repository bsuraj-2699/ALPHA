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
    Primary model id. Default ``meta/llama-3.2-90b-vision-instruct``.
LLM_FALLBACK_MODEL
    Fallback model id used when the primary call fails (quota / outage / error).
    Default ``meta/llama-3.2-90b-vision-instruct``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Env vars stripped by eval/offline helpers so templated fallbacks run.
LLM_API_KEY_ENV_NAMES: tuple[str, ...] = (
    "LLM_API_KEY",
    "LLM_API_BASE",
)

DEFAULT_API_BASE = "https://integrate.api.nvidia.com/v1"
# Both must support tool/function calling: instructor needs structured output,
# and most NIM catalogue models fail it (InstructorRetryException) or are not
# entitled for a given account (404 "Function ... not found"), while a retired
# id returns 410 (see ``is_model_retired_error``). Re-probe with a real
# ``provider.complete(response_model=...)`` call before changing either id.
DEFAULT_PRIMARY_MODEL = "meta/llama-3.2-90b-vision-instruct"
DEFAULT_FALLBACK_MODEL = "meta/llama-3.2-90b-vision-instruct"

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


# HTTP status a host returns for a model id that has been withdrawn (NVIDIA
# retired ``nvidia/nvidia-nemotron-nano-9b-v2`` on 2026-08-26). Unlike a 429 or
# a 5xx this is permanent: the same id can never succeed on a retry, so it must
# not be fed to instructor's re-prompt loop — 3 attempts x 8 narrators is 24
# pointless round trips per run. Fail fast and let failover reach the fallback.
MODEL_RETIRED_STATUS = 410


def _status_code_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an SDK exception (litellm / openai / httpx)."""
    candidates: list[Any] = [
        getattr(exc, "status_code", None),
        getattr(exc, "http_status", None),
        getattr(exc, "code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ]
    for raw in candidates:
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
        # openai's ``code`` is usually a slug ("model_not_found"); litellm
        # sometimes stringifies the status instead.
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
    return None


def is_model_retired_error(exc: BaseException | None) -> bool:
    """True when ``exc`` (or anything it wraps) is an HTTP 410 from the endpoint.

    Walks ``__cause__``/``__context__`` because litellm re-raises provider
    errors and instructor wraps the last attempt in ``InstructorRetryException``.
    """
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if _status_code_of(exc) == MODEL_RETIRED_STATUS:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def instructor_retry_policy(max_attempts: int, timeout: float | None = None) -> Any:
    """``AsyncRetrying`` for ``instructor``: re-prompt on bad output, not on a 410.

    Mirrors the policy instructor builds for a plain ``max_retries=N`` (stop
    after ``max_attempts``, and after ``timeout`` seconds in total) but adds a
    retry predicate. instructor's async retry loop re-raises *every* exception
    inside the tenacity attempt — API errors included — so without this a
    retired model id burns the full attempt budget before failing over.

    When the predicate declines, tenacity re-raises the original error rather
    than wrapping it in ``RetryError``, so the caller sees the real 410.
    """
    from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, stop_after_delay

    stop = stop_after_attempt(max_attempts)
    if timeout is not None:
        stop = stop | stop_after_delay(timeout)
    return AsyncRetrying(
        stop=stop,
        retry=retry_if_exception(lambda e: not is_model_retired_error(e)),
    )


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
    "MODEL_RETIRED_STATUS",
    "api_base",
    "api_key",
    "fallback_model",
    "get_litellm_instructor_client",
    "instructor_retry_policy",
    "is_any_llm_configured",
    "is_model_retired_error",
    "llm_env_stripped_offline",
    "model_ids",
    "primary_model",
]

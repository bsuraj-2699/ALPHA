"""LangSmith tracing wiring for the agent runtime.

Enabling tracing is a configuration decision: set ``LANGSMITH_API_KEY`` and the
LiteLLM LangSmith callback captures every model call (prompt, response, tokens,
latency) under ``LANGSMITH_PROJECT``. With no key present this is a no-op, so
offline and CI runs are unaffected.

Environment
-----------
LANGSMITH_API_KEY   API key from smith.langchain.com (required to enable).
LANGSMITH_PROJECT   Project name for traces. Default ``alpha-fin-agent``.
LANGSMITH_TRACING   Set to ``false`` to disable even when a key is present.
LANGSMITH_ENDPOINT  Optional self-hosted LangSmith endpoint.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialised = False


def _truthy(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_tracing_enabled() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY", "").strip()) and _truthy(
        "LANGSMITH_TRACING", True
    )


def init_tracing() -> bool:
    """Enable the LiteLLM LangSmith callback once. Returns whether tracing is on.

    Idempotent and safe to call from multiple entry points (the instructor
    client factory and the API lifespan).
    """
    global _initialised
    if _initialised:
        return is_tracing_enabled()
    _initialised = True

    if not is_tracing_enabled():
        return False

    os.environ.setdefault("LANGSMITH_PROJECT", "alpha-fin-agent")
    # LangSmith's SDK also reads the LANGCHAIN_* aliases; keep them in sync.
    os.environ.setdefault("LANGCHAIN_PROJECT", os.environ["LANGSMITH_PROJECT"])
    os.environ.setdefault("LANGCHAIN_API_KEY", os.environ["LANGSMITH_API_KEY"])
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

    try:
        import litellm

        callbacks = list(getattr(litellm, "callbacks", []) or [])
        if "langsmith" not in callbacks:
            callbacks.append("langsmith")
        litellm.callbacks = callbacks
        logger.info(
            "LangSmith tracing enabled (project=%s)",
            os.environ["LANGSMITH_PROJECT"],
        )
        return True
    except Exception as e:  # pragma: no cover - tracing must never break a run
        logger.warning("LangSmith tracing not enabled: %s", e)
        return False


__all__ = ["init_tracing", "is_tracing_enabled"]

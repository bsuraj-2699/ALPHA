"""Runtime configuration for the API.

Reads environment variables with sensible defaults so the app boots in any
environment (laptop, docker-compose, prod). All variables are optional; a
missing DATABASE_URL etc. just means that subsystem stays in-memory and the
``/health`` endpoint reports it as ``not_configured``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # External services. Empty string == not configured (in-memory fallback).
    database_url: str = ""  # postgresql+asyncpg://user:pass@host:5432/db
    redis_url: str = ""  # redis://host:6379/0
    qdrant_url: str = ""  # http://host:6333

    # Orchestrator behavior
    auto_approve_strong_signals: bool = False
    openai_model: str = "gpt-4o"

    # Idempotency window: dedupe duplicate POSTs within this many hours.
    idempotency_ttl_hours: int = 24

    # SSE keep-alive: send a comment ping every N seconds to keep proxies
    # from killing the connection.
    sse_keepalive_seconds: int = 15

    # Comma-separated list of origins allowed to call the API from a
    # browser. Defaults to the local Next.js dev server. Set
    # ``ALLOW_ORIGINS=*`` to allow any origin (development only).
    allow_origins: str = "http://localhost:3000,http://127.0.0.1:3000"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", ""),
        redis_url=os.getenv("REDIS_URL", ""),
        qdrant_url=os.getenv("QDRANT_URL", ""),
        auto_approve_strong_signals=_env_bool(
            "AUTO_APPROVE_STRONG_SIGNALS", False
        ),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        idempotency_ttl_hours=_env_int("IDEMPOTENCY_TTL_HOURS", 24),
        sse_keepalive_seconds=_env_int("SSE_KEEPALIVE_SECONDS", 15),
        allow_origins=os.getenv(
            "ALLOW_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ),
    )


__all__ = ["Settings", "load_settings"]

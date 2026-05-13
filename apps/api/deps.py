"""Dependency-injection helpers for FastAPI routes.

The app stores its singletons on ``app.state`` so each request fetches the
same instances. Tests can replace any singleton via the ``override_state``
helper before the test client makes its first request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:  # pragma: no cover
    from packages.agents.orchestrator import Orchestrator

    from apps.api.buckets import BucketStore
    from apps.api.config import Settings
    from apps.api.db import RunLogStore
    from apps.api.events import EventBus
    from apps.api.idempotency import IdempotencyCache
    from apps.api.runs import RunManager


def get_settings(request: Request) -> "Settings":
    return request.app.state.settings  # type: ignore[no-any-return]


def get_orchestrator(request: Request) -> "Orchestrator":
    return request.app.state.orchestrator  # type: ignore[no-any-return]


def get_event_bus(request: Request) -> "EventBus":
    return request.app.state.event_bus  # type: ignore[no-any-return]


def get_log_store(request: Request) -> "RunLogStore":
    return request.app.state.log_store  # type: ignore[no-any-return]


def get_idempotency_cache(request: Request) -> "IdempotencyCache":
    return request.app.state.idempotency_cache  # type: ignore[no-any-return]


def get_run_manager(request: Request) -> "RunManager":
    return request.app.state.run_manager  # type: ignore[no-any-return]


def get_watchlist(request: Request) -> list[Any]:
    return request.app.state.watchlist  # type: ignore[no-any-return]


def get_portfolio(request: Request) -> list[Any]:
    return request.app.state.portfolio  # type: ignore[no-any-return]


def get_bucket_store(request: Request) -> "BucketStore":
    return request.app.state.bucket_store  # type: ignore[no-any-return]


__all__ = [
    "get_bucket_store",
    "get_event_bus",
    "get_idempotency_cache",
    "get_log_store",
    "get_orchestrator",
    "get_portfolio",
    "get_run_manager",
    "get_settings",
    "get_watchlist",
]

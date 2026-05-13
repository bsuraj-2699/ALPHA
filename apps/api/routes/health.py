"""Health check endpoint.

Pings each external dependency with a short timeout and reports per-service
status. The aggregate ``status`` is ``ok`` if everything configured is up,
``degraded`` if any configured service is down, and ``not_configured`` /
``ok`` otherwise.

When a service isn't configured (e.g. no ``DATABASE_URL`` set) we report
``not_configured`` rather than failing — this is the expected state in
local development.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Request

from apps.api.deps import (
    get_event_bus,
    get_log_store,
    get_settings,
)
from apps.api.events import EventBus
from apps.api.db import RunLogStore
from apps.api.models import HealthResponse, HealthService

router = APIRouter()


_PING_TIMEOUT = 2.0  # seconds


async def _ping(coro_factory) -> tuple[float, Exception | None]:  # type: ignore[no-untyped-def]
    """Run ``await coro_factory()`` with timeout; return (latency_ms, error)."""
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(coro_factory(), timeout=_PING_TIMEOUT)
    except Exception as e:
        return (time.perf_counter() - t0) * 1000, e
    return (time.perf_counter() - t0) * 1000, None


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    settings=Depends(get_settings),
    bus: EventBus = Depends(get_event_bus),
    log_store: RunLogStore = Depends(get_log_store),
) -> HealthResponse:
    subsystem_status: dict[str, str] = getattr(
        request.app.state, "subsystem_status", {}
    )
    services: dict[str, HealthService] = {}

    # Postgres
    if subsystem_status.get("postgres") == "configured":
        latency, err = await _ping(log_store.ping)
        services["postgres"] = HealthService(
            status="ok" if err is None else "down",
            latency_ms=round(latency, 2),
            error=str(err) if err else None,
        )
    else:
        services["postgres"] = HealthService(status="not_configured")

    # Redis (used by both event bus and idempotency cache; one ping covers
    # both since they share a connection in practice).
    if subsystem_status.get("redis") == "configured":
        latency, err = await _ping(bus.ping)
        services["redis"] = HealthService(
            status="ok" if err is None else "down",
            latency_ms=round(latency, 2),
            error=str(err) if err else None,
        )
    else:
        services["redis"] = HealthService(status="not_configured")

    # Qdrant
    if settings.qdrant_url:
        services["qdrant"] = await _ping_qdrant(settings.qdrant_url)
    else:
        services["qdrant"] = HealthService(status="not_configured")

    # Aggregate.
    statuses = [s.status for s in services.values()]
    if any(s == "down" for s in statuses):
        overall = "degraded"
    elif all(s == "not_configured" for s in statuses):
        # Pure dev mode — everything in-memory; report as ``ok`` so liveness
        # probes pass, but ``services`` makes the dev posture transparent.
        overall = "ok"
    else:
        overall = "ok"
    return HealthResponse(status=overall, services=services)  # type: ignore[arg-type]


async def _ping_qdrant(qdrant_url: str) -> HealthService:
    import httpx

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_PING_TIMEOUT) as client:
            resp = await client.get(f"{qdrant_url.rstrip('/')}/readyz")
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            return HealthService(status="ok", latency_ms=round(latency, 2))
        return HealthService(
            status="down",
            latency_ms=round(latency, 2),
            error=f"HTTP {resp.status_code}",
        )
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        return HealthService(
            status="down", latency_ms=round(latency, 2), error=str(e)
        )

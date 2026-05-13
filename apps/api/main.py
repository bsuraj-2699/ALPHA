"""FastAPI app factory.

Lifespan responsibilities:

  * Build the singletons the routes depend on (orchestrator, event bus,
    log store, idempotency cache, run manager).
  * Wire the LangGraph Redis checkpointer when ``REDIS_URL`` is set;
    otherwise fall back to ``MemorySaver`` (development / tests).
  * Initialize the Postgres ``run_logs`` table when ``DATABASE_URL`` is
    set; otherwise use the in-memory log store.
  * Cleanly tear everything down on shutdown.

Tests should construct the app via :func:`create_app` and override any
state singleton on ``app.state`` BEFORE the test client makes its first
request. See ``apps/api/tests/conftest.py``.
"""

from __future__ import annotations
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.memory import MemorySaver

from packages.agents.orchestrator import Orchestrator
from packages.data.providers.cache import RedisCache
from packages.data.providers.upstox_auth import refresh_access_token

from apps.api.buckets import BucketStore, InMemoryBucketStore, RedisBucketStore
from apps.api.config import Settings, load_settings
from apps.api.db import InMemoryRunLogStore, PostgresRunLogStore, RunLogStore
from apps.api.events import EventBus, InMemoryEventBus, RedisEventBus
from apps.api.idempotency import (
    IdempotencyCache,
    InMemoryIdempotencyCache,
    RedisIdempotencyCache,
)
from apps.api.retrigger import RetriggerSubscriber
from apps.api.routes import (
    analyze as analyze_routes,
    buckets as buckets_routes,
    health as health_routes,
    portfolio as portfolio_routes,
    price as price_routes,
    runs as runs_routes,
    watchlist as watchlist_routes,
)
from apps.api.runs import RunManager
from apps.api.scheduler import DailyScheduler, IntradayScheduler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Subsystem builders
# ---------------------------------------------------------------------------


async def _build_log_store(settings: Settings) -> tuple[RunLogStore, bool]:
    """Returns (store, was_postgres). ``was_postgres=False`` means the
    in-memory fallback is in use; ``/health`` reports it as ``not_configured``."""
    if not settings.database_url:
        return InMemoryRunLogStore(), False
    try:
        store = PostgresRunLogStore.from_url(settings.database_url)
        await store.init_schema()
        await store.ping()
    except Exception as e:
        logger.warning(
            "Postgres at %s unavailable (%s); falling back to in-memory log store",
            settings.database_url,
            e,
        )
        return InMemoryRunLogStore(), False
    return store, True


async def _build_event_bus_and_idempotency(
    settings: Settings,
) -> tuple[EventBus, IdempotencyCache, bool]:
    """Returns (bus, cache, was_redis). When Redis is unavailable both fall
    back to in-memory adapters that share no state across processes."""
    if not settings.redis_url:
        return InMemoryEventBus(), InMemoryIdempotencyCache(), False
    try:
        bus = RedisEventBus.from_url(settings.redis_url)
        await bus.ping()
        cache = RedisIdempotencyCache.from_url(settings.redis_url)
    except Exception as e:
        logger.warning(
            "Redis at %s unavailable (%s); falling back to in-memory adapters",
            settings.redis_url,
            e,
        )
        return InMemoryEventBus(), InMemoryIdempotencyCache(), False
    return bus, cache, True


async def _build_bucket_store(
    settings: Settings, redis_ok: bool
) -> BucketStore:
    """Redis-backed when configured, else in-memory.

    The in-memory variant is fine for local dev — buckets just don't
    survive a process restart. Redis is shared across worker processes
    so the scheduler picks up bucket edits made through any worker.
    """
    if not (redis_ok and settings.redis_url):
        return InMemoryBucketStore()
    try:
        return RedisBucketStore.from_url(settings.redis_url)
    except Exception as e:  # pragma: no cover
        logger.warning(
            "Redis bucket store unavailable (%s); using in-memory fallback", e
        )
        return InMemoryBucketStore()


# ---------------------------------------------------------------------------
# Upstox daily token refresh
# ---------------------------------------------------------------------------


def _seconds_until_next_9am_ist() -> float:
    """Seconds from now until the next 09:00 IST (03:30 UTC).

    Upstox access tokens expire at 03:30 UTC; we refresh slightly after
    that. Returns a non-zero positive value so the first sleep always
    waits — the initial refresh runs separately on startup.
    """
    now = datetime.now(UTC)
    target = now.replace(hour=3, minute=30, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return (target - now).total_seconds()


async def _upstox_refresh_loop(cache: RedisCache) -> None:
    """Background task: refresh the Upstox access token once on boot,
    then once per day at 09:00 IST. Failures are logged and the loop
    keeps running."""
    try:
        await refresh_access_token(cache)
    except Exception as e:  # pragma: no cover
        logger.warning("initial upstox refresh failed: %s", e)
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_9am_ist())
        except asyncio.CancelledError:
            return
        try:
            await refresh_access_token(cache)
        except Exception as e:  # pragma: no cover
            logger.warning("scheduled upstox refresh failed: %s", e)


async def _build_checkpointer(settings: Settings) -> tuple[Any, bool]:
    """Returns (checkpointer, was_redis)."""
    if not settings.redis_url:
        return MemorySaver(), False
    try:
        from langgraph.checkpoint.redis.aio import AsyncRedisSaver

        # langgraph-checkpoint-redis exposes a context-manager factory; we
        # enter it and never exit so the saver lives for the app's lifetime.
        cm = AsyncRedisSaver.from_conn_string(settings.redis_url)
        saver = await cm.__aenter__()
        # Index/schema setup (idempotent).
        try:
            await saver.asetup()
        except AttributeError:  # pragma: no cover - older API
            pass
        # Stash the cm so we can exit it on shutdown.
        saver._cm = cm  # type: ignore[attr-defined]
        return saver, True
    except Exception as e:
        logger.warning(
            "LangGraph Redis checkpointer unavailable (%s); using MemorySaver", e
        )
        return MemorySaver(), False


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    log_store, db_ok = await _build_log_store(settings)
    bus, idem, redis_ok = await _build_event_bus_and_idempotency(settings)
    checkpointer, ckpt_redis_ok = await _build_checkpointer(settings)
    bucket_store = await _build_bucket_store(settings, redis_ok)

    # Allow create_app(context_builder=...) / create_app(orchestrator=...)
    # to inject test fakes. Real callers leave both at None.
    orch_override = getattr(app.state, "_orchestrator_override", None)
    cb_override = getattr(app.state, "_context_builder_override", None)
    if orch_override is not None:
        orch = orch_override
    else:
        orch = Orchestrator(
            context_builder=cb_override,
            checkpointer=checkpointer,
            auto_approve_strong_signals=settings.auto_approve_strong_signals,
            openai_model=settings.openai_model,
        )
    run_manager = RunManager(orch, bus, log_store)

    # Daily Upstox token refresh — kicks off an initial exchange now and
    # then re-runs at 09:00 IST. The provider reads from Redis so the new
    # token propagates without a process restart.
    upstox_cache = RedisCache(settings.redis_url)
    upstox_task = asyncio.create_task(_upstox_refresh_loop(upstox_cache))

    # Retrigger subscriber — listens on Redis ``retrigger:*`` for events
    # the Upstox WS adapter publishes when a tick crosses the price /
    # volume thresholds, and spawns intraday runs for the matching ticker
    # (subject to a 60s completion cooldown). Only wired when Redis is
    # actually available; in-memory mode skips the subscriber.
    retrigger_redis: Any | None = None
    retrigger_subscriber: RetriggerSubscriber | None = None
    if redis_ok and settings.redis_url:
        try:
            import redis.asyncio as redis_async

            retrigger_redis = redis_async.from_url(
                settings.redis_url, decode_responses=True
            )
            retrigger_subscriber = RetriggerSubscriber(retrigger_redis, run_manager)
            retrigger_subscriber.start()
        except Exception as e:  # pragma: no cover
            logger.warning("retrigger subscriber not started: %s", e)
            retrigger_subscriber = None

    # Bucket-driven schedulers — every 5 min during NSE hours for the
    # intraday bucket, and once per business day at 10:00 IST for the
    # short_term + long_term buckets. Both bypass the daily idempotency
    # cache by minting their own run ids.
    intraday_scheduler = IntradayScheduler(bucket_store, run_manager)
    daily_scheduler = DailyScheduler(bucket_store, run_manager)
    intraday_scheduler.start()
    daily_scheduler.start()

    app.state.log_store = log_store
    app.state.event_bus = bus
    app.state.idempotency_cache = idem
    app.state.checkpointer = checkpointer
    app.state.orchestrator = orch
    app.state.run_manager = run_manager
    app.state.upstox_refresh_task = upstox_task
    app.state.retrigger_subscriber = retrigger_subscriber
    app.state.bucket_store = bucket_store
    app.state.intraday_scheduler = intraday_scheduler
    app.state.daily_scheduler = daily_scheduler
    # In-memory stores for the non-critical endpoints.
    app.state.watchlist = []
    app.state.portfolio = []
    # For /health to know what's configured vs in-memory:
    app.state.subsystem_status = {
        "postgres": "configured" if db_ok else "not_configured",
        "redis": "configured" if redis_ok else "not_configured",
        "redis_checkpointer": "configured" if ckpt_redis_ok else "not_configured",
    }

    try:
        yield
    finally:
        upstox_task.cancel()
        try:
            await upstox_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await upstox_cache.aclose()
        except Exception:
            pass
        if retrigger_subscriber is not None:
            await retrigger_subscriber.stop()
        if retrigger_redis is not None:
            try:
                await retrigger_redis.aclose()
            except Exception:
                pass
        for scheduler in (intraday_scheduler, daily_scheduler):
            try:
                await scheduler.stop()
            except Exception:  # pragma: no cover
                pass
        try:
            await bucket_store.close()
        except Exception:  # pragma: no cover
            pass
        await run_manager.shutdown()
        for closer in (bus, log_store):
            try:
                await closer.close()  # type: ignore[union-attr]
            except Exception:
                pass
        cm = getattr(checkpointer, "_cm", None)
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception:  # pragma: no cover
                pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    orchestrator: Orchestrator | None = None,
    context_builder: Any = None,
) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title="fin-agent API",
        version="0.1.0",
        description="Multi-agent financial analysis HTTP layer.",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    # Test injection points (None in production).
    app.state._orchestrator_override = orchestrator
    app.state._context_builder_override = context_builder

    # CORS: allow the Next.js dev server (and any explicitly-configured
    # origins) to call the API from the browser. Allowed methods cover
    # everything we currently expose; SSE specifically needs ``GET`` and
    # the headers EventSource sends by default.
    raw_origins = [o.strip() for o in settings.allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=raw_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router, tags=["health"])
    app.include_router(analyze_routes.router, prefix="/api", tags=["analyze"])
    app.include_router(runs_routes.router, prefix="/api", tags=["runs"])
    app.include_router(price_routes.router, prefix="/api", tags=["price"])
    app.include_router(portfolio_routes.router, prefix="/api", tags=["portfolio"])
    app.include_router(watchlist_routes.router, prefix="/api", tags=["watchlist"])
    app.include_router(buckets_routes.router, prefix="/api", tags=["buckets"])

    return app


# Instance for ``uvicorn apps.api.main:app``.
app = create_app()


__all__ = ["app", "create_app"]

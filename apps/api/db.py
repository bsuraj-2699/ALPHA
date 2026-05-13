"""Postgres-backed run-log storage.

Schema is intentionally minimal — one row per orchestrator run in
``run_logs``, capturing audit fields (run_id, ticker, LLM tokens, cost,
latency, signal, status, error).

The companion ``intraday_signals`` table holds **only** actionable
intraday outcomes (BUY / STRONG_BUY / SELL / STRONG_SELL). Application
logic in :mod:`apps.api.runs` gates those inserts. Every intraday run
still writes a ``run_logs`` row on completion (including **HOLD**) so
scheduled ticks are auditable and appear in Excel exports.

When ``DATABASE_URL`` isn't configured, :class:`RunLogStore` returns a
no-op implementation so the API still works (logs go to stdout). The
``/health`` endpoint reports the DB as ``not_configured`` in that case.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)


_metadata = MetaData()

run_logs = Table(
    "run_logs",
    _metadata,
    Column("run_id", String(64), primary_key=True),
    Column("ticker", String(12), nullable=False),
    Column("market", String(2), nullable=False),
    Column("status", String(16), nullable=False),
    Column("final_signal", String(16), nullable=True),
    Column("overrides_active", Text, nullable=True),  # JSON-encoded list
    Column("requires_human_review", String(8), nullable=True),  # 'true' / 'false'
    Column("llm_tokens_in", Integer, nullable=False, default=0),
    Column("llm_tokens_out", Integer, nullable=False, default=0),
    Column("llm_cost_usd", Numeric(10, 6), nullable=False, default=0),
    Column("latency_ms", Integer, nullable=False, default=0),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("error", Text, nullable=True),
)


intraday_signals = Table(
    "intraday_signals",
    _metadata,
    Column(
        "id",
        BigInteger,
        Identity(always=True),
        primary_key=True,
    ),
    Column("run_id", String(64), nullable=False, unique=True),
    Column("ticker", String(12), nullable=False),
    Column("signal", String(16), nullable=False),
    Column("composite_score", Numeric(6, 2), nullable=False),
    Column("confidence", Numeric(6, 2), nullable=False),
    Column("entry_price", Numeric(18, 6), nullable=True),
    Column("stop_loss", Numeric(18, 6), nullable=True),
    Column("target_price", Numeric(18, 6), nullable=True),
    Column("data_coverage_pct", Numeric(6, 2), nullable=True),
    Column("mode", String(16), nullable=False),
    Column("primary_interval", String(32), nullable=False),
    Column("timestamp", DateTime(timezone=True), nullable=False),
)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


@dataclass
class RunLogEntry:
    run_id: str
    ticker: str
    market: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    final_signal: str | None = None
    overrides_active: list[str] = field(default_factory=list)
    requires_human_review: bool | None = None
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None


@dataclass
class IntradaySignalRow:
    """One row in ``intraday_signals`` — actionable intraday BUY/SELL outcomes."""

    run_id: str
    ticker: str
    signal: str
    composite_score: float
    confidence: float
    entry_price: float | None
    stop_loss: float | None
    target_price: float | None
    data_coverage_pct: float | None
    mode: str
    primary_interval: str
    timestamp: datetime


class RunLogStore(Protocol):
    """Persistence interface for run audit rows. Implementations must be
    safe to call from any async context."""

    async def upsert(self, entry: RunLogEntry) -> None: ...
    async def get(self, run_id: str) -> RunLogEntry | None: ...
    async def ping(self) -> None: ...


# ---------------------------------------------------------------------------
# Postgres implementation
# ---------------------------------------------------------------------------


class PostgresRunLogStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "PostgresRunLogStore":
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(url, pool_pre_ping=True, future=True)
        return cls(engine)

    async def init_schema(self) -> None:
        """Create the run_logs table if it doesn't exist. Called from the
        FastAPI lifespan so a fresh database becomes usable on first boot."""
        async with self._engine.begin() as conn:
            await conn.run_sync(_metadata.create_all)

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def upsert(self, entry: RunLogEntry) -> None:
        stmt = pg_insert(run_logs).values(
            run_id=entry.run_id,
            ticker=entry.ticker,
            market=entry.market,
            status=entry.status,
            final_signal=entry.final_signal,
            overrides_active=json.dumps(entry.overrides_active),
            requires_human_review=(
                None
                if entry.requires_human_review is None
                else ("true" if entry.requires_human_review else "false")
            ),
            llm_tokens_in=entry.llm_tokens_in,
            llm_tokens_out=entry.llm_tokens_out,
            llm_cost_usd=entry.llm_cost_usd,
            latency_ms=entry.latency_ms,
            started_at=entry.started_at,
            completed_at=entry.completed_at,
            error=entry.error,
        )
        # Idempotent on run_id: re-insert overwrites the existing row.
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id"],
            set_={
                "status": stmt.excluded.status,
                "final_signal": stmt.excluded.final_signal,
                "overrides_active": stmt.excluded.overrides_active,
                "requires_human_review": stmt.excluded.requires_human_review,
                "llm_tokens_in": stmt.excluded.llm_tokens_in,
                "llm_tokens_out": stmt.excluded.llm_tokens_out,
                "llm_cost_usd": stmt.excluded.llm_cost_usd,
                "latency_ms": stmt.excluded.latency_ms,
                "completed_at": stmt.excluded.completed_at,
                "error": stmt.excluded.error,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def insert_intraday_signal(self, row: IntradaySignalRow) -> None:
        """Upsert into ``intraday_signals`` keyed by ``run_id``.

        Resume-after-interrupt can finalize the same ``run_id`` twice;
        ``ON CONFLICT`` keeps a single row per run.
        """
        stmt = pg_insert(intraday_signals).values(
            run_id=row.run_id,
            ticker=row.ticker,
            signal=row.signal,
            composite_score=row.composite_score,
            confidence=row.confidence,
            entry_price=row.entry_price,
            stop_loss=row.stop_loss,
            target_price=row.target_price,
            data_coverage_pct=row.data_coverage_pct,
            mode=row.mode,
            primary_interval=row.primary_interval,
            timestamp=row.timestamp,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["run_id"],
            set_={
                "ticker": stmt.excluded.ticker,
                "signal": stmt.excluded.signal,
                "composite_score": stmt.excluded.composite_score,
                "confidence": stmt.excluded.confidence,
                "entry_price": stmt.excluded.entry_price,
                "stop_loss": stmt.excluded.stop_loss,
                "target_price": stmt.excluded.target_price,
                "data_coverage_pct": stmt.excluded.data_coverage_pct,
                "mode": stmt.excluded.mode,
                "primary_interval": stmt.excluded.primary_interval,
                "timestamp": stmt.excluded.timestamp,
            },
        )
        async with self._engine.begin() as conn:
            await conn.execute(stmt)

    async def get(self, run_id: str) -> RunLogEntry | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(run_logs).where(run_logs.c.run_id == run_id))
            ).first()
        if row is None:
            return None
        return RunLogEntry(
            run_id=row.run_id,
            ticker=row.ticker,
            market=row.market,
            status=row.status,
            started_at=row.started_at,
            completed_at=row.completed_at,
            final_signal=row.final_signal,
            overrides_active=json.loads(row.overrides_active or "[]"),
            requires_human_review=(
                None
                if row.requires_human_review is None
                else row.requires_human_review == "true"
            ),
            llm_tokens_in=row.llm_tokens_in,
            llm_tokens_out=row.llm_tokens_out,
            llm_cost_usd=float(row.llm_cost_usd),
            latency_ms=row.latency_ms,
            error=row.error,
        )

    async def close(self) -> None:
        await self._engine.dispose()


# ---------------------------------------------------------------------------
# In-memory fallback (used when DATABASE_URL is unset and in tests)
# ---------------------------------------------------------------------------


class InMemoryRunLogStore:
    def __init__(self) -> None:
        self._rows: dict[str, RunLogEntry] = {}
        self._intraday_signals: dict[str, IntradaySignalRow] = {}

    async def ping(self) -> None:
        return

    async def upsert(self, entry: RunLogEntry) -> None:
        # Persist a fresh copy so callers mutating their entry post-write
        # don't tamper with our store.
        self._rows[entry.run_id] = RunLogEntry(**entry.__dict__)
        logger.debug(
            "run_log %s status=%s tokens=%d cost_usd=%.4f latency_ms=%d",
            entry.run_id,
            entry.status,
            entry.llm_tokens_in + entry.llm_tokens_out,
            entry.llm_cost_usd,
            entry.latency_ms,
        )

    async def get(self, run_id: str) -> RunLogEntry | None:
        row = self._rows.get(run_id)
        if row is None:
            return None
        return RunLogEntry(**row.__dict__)

    async def insert_intraday_signal(self, row: IntradaySignalRow) -> None:
        """Mirror Postgres upsert semantics — last write wins per ``run_id``."""
        self._intraday_signals[row.run_id] = IntradaySignalRow(**row.__dict__)

    async def close(self) -> None:
        self._rows.clear()
        self._intraday_signals.clear()


__all__ = [
    "InMemoryRunLogStore",
    "IntradaySignalRow",
    "PostgresRunLogStore",
    "RunLogEntry",
    "RunLogStore",
    "intraday_signals",
    "run_logs",
]

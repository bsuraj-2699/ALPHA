"""Run lifecycle manager.

Owns the lifecycle of an orchestrator invocation behind a
non-blocking API. Responsibilities:

  * Spawn an asyncio task that calls :meth:`Orchestrator.arun`.
  * Bind a per-run :class:`TokenLedger` and event publisher so the agents
    can emit usage / SSE events without explicit plumbing.
  * Track the resulting state in an in-memory record map for
    ``GET /api/runs/{run_id}``.
  * Persist rows in Postgres via :class:`RunLogStore` — every terminal run
    upserts ``run_logs``; actionable intraday outcomes also insert
    ``intraday_signals``.
  * Always publish a ``_terminal_`` event on completion so SSE consumers
    close cleanly.

For human-in-the-loop, ``approve(run_id, response)`` spawns a second task
that calls :meth:`Orchestrator.aresume` and reuses all the same plumbing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from packages.agents.orchestrator import Orchestrator
from packages.shared.config import get_mode_config
from packages.shared.observability import (
    TokenLedger,
    reset_token_ledger,
    set_token_ledger,
)

from apps.api.db import IntradaySignalRow, RunLogEntry, RunLogStore
from apps.api.events import EventBus
from apps.api.serializers import extract_interrupt, serialize_state

logger = logging.getLogger(__name__)


def _canonical_ticker(ticker: str) -> str:
    """Uppercase symbol without ``.NS`` / ``.BO`` for stable equality.

    Buckets and the intraday scheduler store bare NSE names (``LT``), while
    ``POST /api/analyze`` and the web client often use ``LT.NS``. Matching
    on this key lets ``latest_for`` / ``last_completed_for`` see both.
    """
    t = ticker.strip().upper()
    if t.endswith(".NS") or t.endswith(".BO"):
        return t.rsplit(".", 1)[0]
    return t


# Actionable intraday outcomes also persist a dedicated ``intraday_signals`` row.
_INTRADAY_PERSIST_SIGNALS = frozenset({"BUY", "STRONG_BUY", "SELL", "STRONG_SELL"})


@dataclass
class RunRecord:
    run_id: str
    ticker: str
    market: str
    status: str  # "pending" | "running" | "interrupted" | "complete" | "error"
    created_at: datetime
    completed_at: datetime | None = None
    state: dict[str, Any] | None = None  # serialized AgentState
    interrupt: dict[str, Any] | None = None
    error: str | None = None
    # Run mode chosen by the caller (intraday / short_term / long_term).
    # We hold it on the record so the orchestrator gets it on start and
    # downstream observability (logs, run summary) can surface it.
    mode: str = "long_term"
    # Internals:
    task: asyncio.Task[Any] | None = field(default=None, repr=False)
    ledger: TokenLedger | None = field(default=None, repr=False)
    started_perf: float = field(default=0.0, repr=False)


def _parse_decision_timestamp(
    decision: dict[str, Any], fallback: datetime | None
) -> datetime:
    raw = decision.get("timestamp")
    if isinstance(raw, str):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    return fallback if fallback is not None else datetime.now(timezone.utc)


def _intraday_signal_row(rec: RunRecord) -> IntradaySignalRow | None:
    """Build a row for ``intraday_signals`` — caller gates on mode/signal."""
    state = rec.state or {}
    decision = state.get("decision") or {}
    judgment = state.get("judgment") or {}
    sig = decision.get("signal")
    if sig not in _INTRADAY_PERSIST_SIGNALS:
        return None

    comp_raw = judgment.get("composite_score")
    if comp_raw is None:
        comp_raw = decision.get("confidence")
    composite_score = float(comp_raw) if comp_raw is not None else 0.0
    confidence = float(decision.get("confidence") or composite_score)

    dc_raw = decision.get("data_coverage_pct")
    data_cov = float(dc_raw) if dc_raw is not None else None

    chart = get_mode_config("intraday").chart_config  # intraday chart defaults

    return IntradaySignalRow(
        run_id=rec.run_id,
        ticker=rec.ticker,
        signal=str(sig),
        composite_score=composite_score,
        confidence=confidence,
        entry_price=(
            float(decision["entry_price"]) if decision.get("entry_price") is not None else None
        ),
        stop_loss=(
            float(decision["stop_loss"]) if decision.get("stop_loss") is not None else None
        ),
        target_price=(
            float(decision["target_price"]) if decision.get("target_price") is not None else None
        ),
        data_coverage_pct=data_cov,
        mode=str(rec.mode),
        primary_interval=chart.primary_interval,
        timestamp=_parse_decision_timestamp(decision, rec.completed_at),
    )


class RunManager:
    def __init__(
        self,
        orchestrator: Orchestrator,
        event_bus: EventBus,
        log_store: RunLogStore,
    ) -> None:
        self._orch = orchestrator
        self._bus = event_bus
        self._log = log_store
        self._records: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()

    # ----- public API -----------------------------------------------------

    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def last_completed_for(self, ticker: str) -> datetime | None:
        """Most recent ``completed_at`` across all runs for ``ticker``.

        Used by the retrigger subscriber to enforce the 60-second cooldown:
        if a run for the same symbol completed inside that window, skip
        spawning a duplicate.
        """
        want = _canonical_ticker(ticker)
        latest: datetime | None = None
        for rec in self._records.values():
            if _canonical_ticker(rec.ticker) != want or rec.completed_at is None:
                continue
            if latest is None or rec.completed_at > latest:
                latest = rec.completed_at
        return latest

    def latest_for(
        self,
        ticker: str,
        mode: str | None = None,
    ) -> RunRecord | None:
        """Most recently created run for ``ticker`` (optionally filtered by mode).

        Used by ``GET /api/runs/latest`` so the Runs page can resolve the
        right detail row for a bucket entry without having to remember
        run ids client-side. We sort on ``created_at`` rather than
        ``completed_at`` so an in-flight run still surfaces — the UI
        wants to show "running" the moment the scheduler dispatches it.
        """
        want = _canonical_ticker(ticker)
        candidates = [
            rec
            for rec in self._records.values()
            if _canonical_ticker(rec.ticker) == want and (mode is None or rec.mode == mode)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda r: r.created_at, reverse=True)
        return candidates[0]

    async def start_run(
        self,
        run_id: str,
        ticker: str,
        market: str,
        portfolio_context: dict[str, Any] | None = None,
        mode: str = "long_term",
    ) -> RunRecord:
        async with self._lock:
            if run_id in self._records:
                # Caller supplied an idempotent key for an in-flight run;
                # surface the existing record rather than spawning a duplicate.
                return self._records[run_id]
            ledger = TokenLedger()
            rec = RunRecord(
                run_id=run_id,
                ticker=ticker,
                market=market,
                status="pending",
                created_at=datetime.now(timezone.utc),
                ledger=ledger,
                started_perf=time.perf_counter(),
                mode=mode,
            )
            self._records[run_id] = rec

        await self._log_pending(rec)

        rec.task = asyncio.create_task(
            self._execute(rec, portfolio_context),
            name=f"run-{run_id}",
        )
        return rec

    async def approve(self, run_id: str, response: str) -> RunRecord:
        rec = self._records.get(run_id)
        if rec is None:
            raise KeyError(run_id)
        if rec.status != "interrupted":
            raise ValueError(
                f"Cannot approve run {run_id} in status={rec.status!r}; "
                f"approve is only valid for 'interrupted' runs."
            )

        rec.status = "running"
        rec.interrupt = None
        rec.task = asyncio.create_task(
            self._resume(rec, response),
            name=f"run-{run_id}-resume",
        )
        return rec

    async def shutdown(self) -> None:
        """Cancel any in-flight tasks. Called from the FastAPI lifespan."""
        for rec in list(self._records.values()):
            if rec.task is not None and not rec.task.done():
                rec.task.cancel()
                try:
                    await rec.task
                except (asyncio.CancelledError, Exception):
                    pass

    # ----- internal -------------------------------------------------------

    async def _execute(
        self,
        rec: RunRecord,
        portfolio_context: dict[str, Any] | None,
    ) -> None:
        rec.status = "running"
        ledger_token: Token[TokenLedger | None] = set_token_ledger(rec.ledger)
        try:
            state = await self._orch.arun(
                query=f"Analyze {rec.ticker}",
                thread_id=rec.run_id,
                ticker=rec.ticker,
                market=rec.market,  # type: ignore[arg-type]
                context_overrides=portfolio_context,
                event_publisher=self._bus.publish,
                mode=rec.mode,  # type: ignore[arg-type]
            )
            await self._handle_terminal(rec, state)
        except asyncio.CancelledError:
            rec.status = "error"
            rec.error = "cancelled"
            await self._log_terminal(rec)
            raise
        except Exception as e:
            logger.exception("Run %s failed", rec.run_id)
            rec.status = "error"
            rec.error = str(e)
            rec.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(rec.run_id, "error", {"error": str(e)})
            await self._log_terminal(rec)
        finally:
            reset_token_ledger(ledger_token)
            await self._bus.publish(rec.run_id, "_terminal_", {})

    async def _resume(self, rec: RunRecord, response: str) -> None:
        ledger_token: Token[TokenLedger | None] = set_token_ledger(rec.ledger)
        try:
            state = await self._orch.aresume(
                rec.run_id,
                response,
                event_publisher=self._bus.publish,
            )
            await self._handle_terminal(rec, state)
        except Exception as e:
            logger.exception("Run %s resume failed", rec.run_id)
            rec.status = "error"
            rec.error = str(e)
            rec.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(rec.run_id, "error", {"error": str(e)})
            await self._log_terminal(rec)
        finally:
            reset_token_ledger(ledger_token)
            await self._bus.publish(rec.run_id, "_terminal_", {})

    async def _handle_terminal(
        self, rec: RunRecord, state: dict[str, Any]
    ) -> None:
        rec.completed_at = datetime.now(timezone.utc)
        rec.state = serialize_state(state)
        interrupt_payload = extract_interrupt(state)
        if interrupt_payload is not None:
            rec.status = "interrupted"
            rec.interrupt = interrupt_payload
            await self._bus.publish(
                rec.run_id, "interrupted", {"interrupt": interrupt_payload}
            )
        elif state.get("error"):
            rec.status = "error"
            rec.error = str(state["error"])
        else:
            rec.status = "complete"
        await self._log_terminal(rec)

    # ----- audit ----------------------------------------------------------

    async def _log_pending(self, rec: RunRecord) -> None:
        """Seed ``run_logs`` with ``pending`` — skipped for intraday so a HOLD
        outcome doesn't leave an orphan pending row we never finalize."""
        if rec.mode == "intraday":
            return
        try:
            await self._log.upsert(
                RunLogEntry(
                    run_id=rec.run_id,
                    ticker=rec.ticker,
                    market=rec.market,
                    status="pending",
                    started_at=rec.created_at,
                )
            )
        except Exception:  # pragma: no cover - audit must never break a run
            logger.exception("Failed to write pending run log for %s", rec.run_id)

    async def _log_terminal(self, rec: RunRecord) -> None:
        ledger = rec.ledger or TokenLedger()
        latency_ms = int((time.perf_counter() - rec.started_perf) * 1000)
        decision = (rec.state or {}).get("decision") or {}

        # Every terminal run hits run_logs (including intraday HOLD) so
        # scheduler ticks export to Excel / audit. intraday_signals stays
        # gated to actionable signals below.
        try:
            await self._log.upsert(
                RunLogEntry(
                    run_id=rec.run_id,
                    ticker=rec.ticker,
                    market=rec.market,
                    status=rec.status,
                    started_at=rec.created_at,
                    completed_at=rec.completed_at,
                    final_signal=decision.get("signal"),
                    overrides_active=list(decision.get("overrides_active") or []),
                    requires_human_review=decision.get("requires_human_review"),
                    llm_tokens_in=ledger.total_input_tokens,
                    llm_tokens_out=ledger.total_output_tokens,
                    llm_cost_usd=ledger.cost_usd(),
                    latency_ms=latency_ms,
                    error=rec.error,
                )
            )
        except Exception:  # pragma: no cover
            logger.exception("Failed to write terminal run log for %s", rec.run_id)

        insert_intraday = getattr(self._log, "insert_intraday_signal", None)
        if (
            insert_intraday is not None
            and rec.mode == "intraday"
            and rec.status == "complete"
            and decision.get("signal") in _INTRADAY_PERSIST_SIGNALS
        ):
            row = _intraday_signal_row(rec)
            if row is not None:
                try:
                    await insert_intraday(row)
                except Exception:  # pragma: no cover
                    logger.exception(
                        "Failed to insert intraday_signals row for %s", rec.run_id
                    )


__all__ = ["RunManager", "RunRecord"]

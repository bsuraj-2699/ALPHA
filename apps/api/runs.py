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

from packages.agents.orchestrator import _PILLAR_TO_STATE_KEY, Orchestrator
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

# Hard ceiling on Stage-2 narration. If the LLM stack stalls, we keep the fast
# deterministic decision and finalize rather than leaving the run "running".
# Whole-of-Stage-2 budget: analysts (1 wave at LLM_MAX_CONCURRENCY >= 5),
# then debate, then judge = 3 sequential waves. Blowing it is not a correctness
# problem: the deterministic decision is already emitted, and enrichment
# degrades to templated prose.
_ENRICH_TIMEOUT_S = 120.0


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
    # Two-stage (Phase 11) internals: TTD milestone + stashed deterministic
    # decision awaiting human approval.
    decision_ready_perf: float = field(default=0.0, repr=False)
    ttd_ms: float | None = field(default=None, repr=False)
    pending_fast: Any | None = field(default=None, repr=False)


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
        """Two-stage execution (Phase 11).

        Stage 1 (critical path): ``arun_fast`` produces the deterministic
        decision and emits it immediately — this is the Time-To-Decision the
        client waits for. Stage 2 (enrichment) runs the LLM narration AFTER
        the decision is already available, so narration never blocks TTD.
        """
        rec.status = "running"
        ledger_token: Token[TokenLedger | None] = set_token_ledger(rec.ledger)
        try:
            fast = await self._orch.arun_fast(
                ticker=rec.ticker,
                market=rec.market,  # type: ignore[arg-type]
                mode=rec.mode,  # type: ignore[arg-type]
                context_overrides=portfolio_context,
                event_publisher=self._bus.publish,
                thread_id=rec.run_id,
            )
            rec.decision_ready_perf = time.perf_counter()
            rec.ttd_ms = int((rec.decision_ready_perf - rec.started_perf) * 1000)
            rec.state = self._fast_state(fast)

            # Actionable intraday outcomes become durable at TTD, not after
            # narration — so the signal is persisted the instant it exists.
            await self._persist_intraday(rec)

            # Human-in-the-loop gate on STRONG signals (deterministic).
            needs_review = (
                fast.decision.requires_human_review
                and not getattr(self._orch, "auto_approve_strong_signals", True)
            )
            if needs_review:
                rec.pending_fast = fast
                rec.status = "interrupted"
                rec.interrupt = {
                    "type": "human_review_required",
                    "ticker": rec.ticker,
                    "market": rec.market,
                    "signal": fast.decision.signal,
                    "confidence": fast.decision.confidence,
                    "position_size_pct": fast.decision.position_size_pct,
                    "prompt": (
                        f"{fast.decision.signal} for {rec.ticker} at confidence "
                        f"{fast.decision.confidence:.1f}/100. Reply 'approve' to "
                        f"finalize or any other text to downgrade to HOLD."
                    ),
                }
                await self._bus.publish(
                    rec.run_id, "interrupted", {"interrupt": rec.interrupt}
                )
                await self._log_terminal(rec)
                return

            # Stage 2 — enrichment (non-blocking relative to TTD).
            await self._enrich_and_finalize(rec, fast)
        except asyncio.CancelledError:
            rec.status = "error"
            rec.error = "cancelled"
            rec.completed_at = datetime.now(timezone.utc)
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
        """Finalize a human-reviewed run against the stashed fast decision.

        No graph replay needed — the decision is already deterministic.
        'approve' keeps it and enriches; anything else downgrades to HOLD.
        """
        ledger_token: Token[TokenLedger | None] = set_token_ledger(rec.ledger)
        try:
            fast = rec.pending_fast
            if fast is None:  # pragma: no cover - defensive
                raise RuntimeError("no pending decision to resume")
            if response.strip().lower() == "approve":
                await self._enrich_and_finalize(rec, fast)
            else:
                held = fast.decision.model_copy(update={
                    "signal": "HOLD",
                    "position_size_pct": 0.0,
                    "entry_price": None,
                    "stop_loss": None,
                    "target_price": None,
                    "requires_human_review": False,
                    "rationale": (
                        "Human reviewer rejected the "
                        f"{fast.decision.signal} recommendation; downgraded to HOLD. "
                        f"Original rationale: {fast.decision.rationale}"
                    ),
                })
                from dataclasses import replace as _replace

                rec.state = self._fast_state(_replace(fast, decision=held))
                rec.status = "complete"
                rec.completed_at = datetime.now(timezone.utc)
                await self._bus.publish(
                    rec.run_id, "decision", held.model_dump(mode="json")
                )
                await self._log_terminal(rec)
            rec.pending_fast = None
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

    async def _enrich_and_finalize(self, rec: RunRecord, fast: Any) -> None:
        """Stage 2: run narration (best-effort) then finalize the run.

        Enrichment failure never loses the decision — we keep the fast
        decision and complete the run regardless.
        """
        try:
            result = await asyncio.wait_for(
                self._orch.arun_enrich(fast, event_publisher=self._bus.publish),
                timeout=_ENRICH_TIMEOUT_S,
            )
            # Build the raw state (model objects), overlay the enrichment
            # artefacts, and serialize ONCE — so the per-pillar analyst reports
            # (each carrying that agent's confidence) get folded into
            # ``analyst_reports`` by serialize_state. Doing this after
            # serialization would silently drop them (Bug: missing agent
            # confidence in the two-stage flow).
            raw = self._fast_state_raw(fast)
            raw["decision"] = result["decision"]
            if result.get("bull_case") is not None:
                raw["bull_case"] = result["bull_case"]
            if result.get("bear_case") is not None:
                raw["bear_case"] = result["bear_case"]
            for rep in result.get("reports", []) or []:
                key = _PILLAR_TO_STATE_KEY.get(getattr(rep, "pillar", ""))
                if key:
                    raw[key] = rep
            rec.state = serialize_state(raw)
        except Exception:  # pragma: no cover - narration is best-effort
            logger.exception("Run %s enrichment failed; keeping fast decision", rec.run_id)
        rec.status = "complete"
        rec.completed_at = datetime.now(timezone.utc)
        await self._log_terminal(rec)

    def _fast_state_raw(self, fast: Any) -> dict[str, Any]:
        """AgentState-shaped dict of model objects (pre-serialization)."""
        return {
            "ticker": fast.decision.ticker,
            "market": fast.decision.market,
            "context": fast.context,
            "evaluation": fast.evaluation,
            "judgment": fast.judgment,
            "decision": fast.decision,
            "historical_memories": (fast.historical or {}).get("cases", []),
            "historical_evidence": fast.historical or {},
            "reasoning_trace": [],
        }

    def _fast_state(self, fast: Any) -> dict[str, Any]:
        """Serialize a FastDecision into the AgentState response shape."""
        return serialize_state(self._fast_state_raw(fast))

    async def _persist_intraday(self, rec: RunRecord) -> None:
        insert_intraday = getattr(self._log, "insert_intraday_signal", None)
        decision = (rec.state or {}).get("decision") or {}
        if (
            insert_intraday is not None
            and rec.mode == "intraday"
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

    async def _handle_terminal(
        self, rec: RunRecord, state: dict[str, Any]
    ) -> None:
        """Finalize a run from a full state dict (graph/legacy path + the
        persistence entry point exercised by the intraday-persistence tests).

        The two-stage :meth:`_execute` finalizes via ``_enrich_and_finalize``
        instead, but this remains the canonical "serialize state + classify
        status + persist" step and is kept working verbatim.
        """
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

"""Run inspection + control routes.

  * GET    /api/runs/{run_id}            - full state snapshot
  * GET    /api/runs/{run_id}/stream     - SSE event stream
  * POST   /api/runs/{run_id}/approve    - resume an interrupted run
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sse_starlette.sse import EventSourceResponse

from apps.api.buckets import BUCKET_MODES
from apps.api.deps import get_event_bus, get_run_manager, get_settings
from apps.api.events import EventBus, TERMINAL_EVENT_TYPES
from apps.api.models import (
    ApproveRequest,
    ApproveResponse,
    LatestRunResponse,
    RunDetail,
)
from apps.api.runs import RunManager, RunRecord
from packages.shared.config import get_mode_config

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record_to_detail(rec: RunRecord) -> RunDetail:
    state = rec.state or {}
    mode = rec.mode or "long_term"
    # Derive chart_config from the mode registry rather than re-reading
    # it off the orchestrator state — the registry is the single source
    # of truth for "what does mode X mean", and a stale checkpoint that
    # predates a mode-config edit will still surface the latest spec.
    try:
        chart_config = get_mode_config(mode).chart_config
    except ValueError:
        chart_config = None
    return RunDetail(
        run_id=rec.run_id,
        ticker=rec.ticker,
        market=rec.market,  # type: ignore[arg-type]
        status=rec.status,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        chart_config=chart_config,
        created_at=rec.created_at,
        completed_at=rec.completed_at,
        decision=state.get("decision"),
        judgment=state.get("judgment"),
        bull_case=state.get("bull_case"),
        bear_case=state.get("bear_case"),
        analyst_reports=state.get("analyst_reports", {}),
        evaluation=state.get("evaluation"),
        reasoning_trace=state.get("reasoning_trace", []),
        error=rec.error,
        interrupt=rec.interrupt,
    )


# ---------------------------------------------------------------------------
# GET /api/runs/latest
# ---------------------------------------------------------------------------


@router.get("/runs/latest", response_model=LatestRunResponse)
async def get_latest_run(
    ticker: str,
    market: str = "IN",
    mode: str | None = None,
    run_manager: RunManager = Depends(get_run_manager),
) -> LatestRunResponse:
    """Resolve the newest run for ``(ticker, mode)``.

    Used by the Runs page to surface the auto-scheduled run without
    having to remember run ids on the client. Returns ``run_id=None``
    (and HTTP 200) when nothing has been dispatched yet — that's a
    valid empty-state for a freshly-added bucket entry, not an error.
    """
    if mode is not None and mode not in BUCKET_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode {mode!r}; expected one of {list(BUCKET_MODES)}",
        )
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    rec = run_manager.latest_for(normalized_ticker, mode=mode)
    if rec is None:
        return LatestRunResponse(
            ticker=normalized_ticker,
            market=market,  # type: ignore[arg-type]
            mode=(mode or "long_term"),  # type: ignore[arg-type]
            run_id=None,
            status=None,
            created_at=None,
            completed_at=None,
        )
    return LatestRunResponse(
        ticker=rec.ticker,
        market=rec.market,  # type: ignore[arg-type]
        mode=rec.mode,  # type: ignore[arg-type]
        run_id=rec.run_id,
        status=rec.status,  # type: ignore[arg-type]
        created_at=rec.created_at,
        completed_at=rec.completed_at,
    )


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    run_manager: RunManager = Depends(get_run_manager),
) -> RunDetail:
    rec = run_manager.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return _record_to_detail(rec)


# ---------------------------------------------------------------------------
# GET /api/runs/{run_id}/stream
# ---------------------------------------------------------------------------


async def _sse_event_generator(
    run_id: str,
    request: Request,
    bus: EventBus,
    keepalive_seconds: int,
) -> AsyncIterator[dict[str, Any]]:
    """Translate bus events -> SSE envelopes.

    Each yielded dict carries ``event`` (the SSE event name, drives client
    dispatch) and ``data`` (JSON-encoded envelope body). The stream closes
    on terminal events or when the client disconnects.
    """
    sub = bus.subscribe(run_id)
    try:
        async for event in sub:
            if await request.is_disconnected():
                break
            event_type = event.get("type", "thinking")
            # Don't surface the internal `_terminal_` marker to clients;
            # it's only there to break the in-process generator loop.
            if event_type == "_terminal_":
                break
            yield {
                "event": event_type,
                "data": json.dumps(event),
                "retry": keepalive_seconds * 1000,
            }
            if event_type in TERMINAL_EVENT_TYPES:
                break
    finally:
        # The async-generator from EventBus.subscribe() needs explicit
        # cleanup; sub.aclose() is called by GC eventually but doing it
        # eagerly avoids leaking the queue between requests.
        aclose = getattr(sub, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # pragma: no cover
                pass


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    run_manager: RunManager = Depends(get_run_manager),
    bus: EventBus = Depends(get_event_bus),
    settings=Depends(get_settings),
) -> EventSourceResponse:
    rec = run_manager.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")

    return EventSourceResponse(
        _sse_event_generator(
            run_id, request, bus, settings.sse_keepalive_seconds
        ),
        ping=settings.sse_keepalive_seconds,
    )


# ---------------------------------------------------------------------------
# POST /api/runs/{run_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/approve",
    response_model=ApproveResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def approve_run(
    run_id: str,
    body: ApproveRequest,
    run_manager: RunManager = Depends(get_run_manager),
) -> ApproveResponse:
    rec = run_manager.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if rec.status != "interrupted":
        raise HTTPException(
            status_code=409,
            detail=(
                f"run {run_id!r} is not awaiting approval "
                f"(status={rec.status!r})"
            ),
        )
    try:
        await run_manager.approve(run_id, body.response)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    # Wait for the resume task to complete so callers get the final signal
    # in a single round-trip. The orchestrator's decide node is fast (no
    # network), so this typically returns within milliseconds.
    if rec.task is not None:
        try:
            await rec.task
        except Exception:  # pragma: no cover - errors already captured on rec
            pass

    final_signal = None
    if rec.state and isinstance(rec.state.get("decision"), dict):
        final_signal = rec.state["decision"].get("signal")
    return ApproveResponse(
        run_id=run_id,
        status=rec.status,  # type: ignore[arg-type]
        final_signal=final_signal,
    )

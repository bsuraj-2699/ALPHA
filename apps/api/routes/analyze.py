"""POST /api/analyze - kick off a LangGraph run in the background.

Idempotency (``short_term`` / ``long_term``): ``sha256(ticker:market:mode:date)``
truncated to 16 hex chars doubles as ``run_id``. A duplicate POST the same UTC
day returns ``idempotent_hit=True`` — no second graph invocation.

``intraday`` bypasses that cache: each POST mints a fresh ``run_id`` so repeated
intraday analyses (and Postgres ``intraday_signals`` / ``run_logs``) are not
suppressed after the first run of the day for a ticker.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.deps import (
    get_idempotency_cache,
    get_run_manager,
    get_settings,
)
from apps.api.idempotency import IdempotencyCache, make_idempotency_key
from apps.api.models import AnalyzeRequest, AnalyzeResponse
from apps.api.runs import RunManager
from packages.shared.config import get_mode_config

router = APIRouter()


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze(
    body: AnalyzeRequest,
    cache: IdempotencyCache = Depends(get_idempotency_cache),
    run_manager: RunManager = Depends(get_run_manager),
    settings=Depends(get_settings),
) -> AnalyzeResponse:
    if body.market != "IN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Only Indian market (IN) is supported in this deployment"},
        )
    chart_config = get_mode_config(body.mode).chart_config

    if body.mode == "intraday":
        run_id = secrets.token_hex(8)
        rec = await run_manager.start_run(
            run_id=run_id,
            ticker=body.ticker,
            market=body.market,
            portfolio_context=body.portfolio_context,
            mode=body.mode,
        )
        return AnalyzeResponse(
            run_id=run_id,
            idempotent_hit=False,
            status=rec.status,  # type: ignore[arg-type]
            mode=body.mode,
            chart_config=chart_config,
        )

    key = make_idempotency_key(body.ticker, body.market, mode=body.mode)
    existing_run_id = await cache.get(key)
    if existing_run_id is not None:
        rec = run_manager.get(existing_run_id)
        if rec is not None:
            # On an idempotent hit we echo the *original* run's mode and chart
            # spec so the response stays consistent with the in-flight job.
            existing_mode = getattr(rec, "mode", body.mode) or body.mode
            existing_chart = (
                get_mode_config(existing_mode).chart_config or chart_config
            )
            return AnalyzeResponse(
                run_id=existing_run_id,
                idempotent_hit=True,
                status=rec.status,  # type: ignore[arg-type]
                mode=existing_mode,  # type: ignore[arg-type]
                chart_config=existing_chart,
            )
        # Stale cache entry (run was evicted). Fall through and start fresh.
        await cache.delete(key)

    run_id = key  # 16-hex idempotency hash doubles as our run_id.
    rec = await run_manager.start_run(
        run_id=run_id,
        ticker=body.ticker,
        market=body.market,
        portfolio_context=body.portfolio_context,
        mode=body.mode,
    )
    await cache.set(key, run_id, ttl_seconds=settings.idempotency_ttl_hours * 3600)

    return AnalyzeResponse(
        run_id=run_id,
        idempotent_hit=False,
        status=rec.status,  # type: ignore[arg-type]
        mode=body.mode,
        chart_config=chart_config,  # type: ignore[arg-type]
    )

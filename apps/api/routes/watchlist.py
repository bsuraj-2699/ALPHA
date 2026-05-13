"""Watchlist endpoints.

Backed by an in-memory list on ``app.state.watchlist``. Adds dedupe by
``(ticker, market)``; subsequent additions of the same pair are no-ops.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status

from apps.api.deps import get_watchlist
from apps.api.models import WatchlistAddRequest, WatchlistItem, WatchlistResponse

router = APIRouter()


@router.get("/watchlist", response_model=WatchlistResponse)
async def list_watchlist(
    items: list[WatchlistItem] = Depends(get_watchlist),
) -> WatchlistResponse:
    return WatchlistResponse(items=list(items))


@router.post(
    "/watchlist",
    response_model=WatchlistItem,
    status_code=status.HTTP_201_CREATED,
)
async def add_watchlist_item(
    body: WatchlistAddRequest,
    items: list[WatchlistItem] = Depends(get_watchlist),
) -> WatchlistItem:
    # Dedupe — POSTing the same (ticker, market) twice returns the
    # original entry (with original ``added_at``) rather than duplicating.
    for existing in items:
        if existing.ticker == body.ticker and existing.market == body.market:
            return existing
    item = WatchlistItem(
        ticker=body.ticker,
        market=body.market,
        added_at=datetime.now(timezone.utc),
    )
    items.append(item)
    return item

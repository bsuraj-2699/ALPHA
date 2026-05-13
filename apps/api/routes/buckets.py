"""Strategy-bucket endpoints.

The Runs page calls these to mirror the user's selection on the server
so the scheduler in :mod:`apps.api.scheduler` can keep them fresh
without a browser tab open. Storage is provided by the
:class:`BucketStore` adapter on ``app.state.bucket_store`` (Redis when
configured, in-memory otherwise).

  * ``GET    /api/buckets``                   — all three buckets at once
  * ``GET    /api/buckets/{mode}``             — one bucket
  * ``POST   /api/buckets/{mode}``             — append tickers (deduped)
  * ``PUT    /api/buckets/{mode}``             — replace bucket wholesale
  * ``DELETE /api/buckets/{mode}/{ticker}``    — drop one ticker
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from apps.api.buckets import BUCKET_MODES, BucketStore
from apps.api.deps import get_bucket_store
from apps.api.models import (
    BucketAddRequest,
    BucketReplaceRequest,
    BucketResponse,
    BucketsResponse,
)

router = APIRouter()


def _validate_mode(mode: str) -> None:
    if mode not in BUCKET_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown mode {mode!r}; expected one of {list(BUCKET_MODES)}",
        )


@router.get("/buckets", response_model=BucketsResponse)
async def list_all_buckets(
    store: BucketStore = Depends(get_bucket_store),
) -> BucketsResponse:
    return BucketsResponse(buckets=await store.all())  # type: ignore[arg-type]


@router.get("/buckets/{mode}", response_model=BucketResponse)
async def get_bucket(
    mode: str,
    store: BucketStore = Depends(get_bucket_store),
) -> BucketResponse:
    _validate_mode(mode)
    return BucketResponse(mode=mode, tickers=await store.list(mode))  # type: ignore[arg-type]


@router.post("/buckets/{mode}", response_model=BucketResponse)
async def add_to_bucket(
    mode: str,
    body: BucketAddRequest,
    store: BucketStore = Depends(get_bucket_store),
) -> BucketResponse:
    _validate_mode(mode)
    tickers = await store.add(mode, body.tickers)
    return BucketResponse(mode=mode, tickers=tickers)  # type: ignore[arg-type]


@router.put("/buckets/{mode}", response_model=BucketResponse)
async def replace_bucket(
    mode: str,
    body: BucketReplaceRequest,
    store: BucketStore = Depends(get_bucket_store),
) -> BucketResponse:
    _validate_mode(mode)
    tickers = await store.replace(mode, body.tickers)
    return BucketResponse(mode=mode, tickers=tickers)  # type: ignore[arg-type]


@router.delete(
    "/buckets/{mode}/{ticker}",
    response_model=BucketResponse,
)
async def remove_from_bucket(
    mode: str,
    ticker: str,
    store: BucketStore = Depends(get_bucket_store),
) -> BucketResponse:
    _validate_mode(mode)
    tickers = await store.remove(mode, ticker)
    return BucketResponse(mode=mode, tickers=tickers)  # type: ignore[arg-type]

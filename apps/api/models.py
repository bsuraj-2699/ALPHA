"""Pydantic request / response models for the public API.

Kept separate from :mod:`packages.shared.schemas` (which holds the
agent-internal data shapes) so the API can evolve at its own cadence and
the validation rules can be tighter (e.g. ticker character class).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.shared.schemas import ChartConfig

# Tickers we accept on the wire: 1-10 alphanumerics, optionally suffixed by
# '.NS' or '.BO' for Indian listings. Tighter than what the orchestrator's
# heuristic parser allows on free-text, because here the client tells us
# the ticker authoritatively.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]*(\.[A-Z]{2})?$")

Market = Literal["IN", "US"]
# Mirrors ``packages.shared.schemas.Mode`` but redeclared locally so the
# API request/response models don't drag the agent-internal schema module
# into client tooling. Keep in sync with ``packages.shared.config.Mode``.
Mode = Literal["intraday", "short_term", "long_term"]


# ---------------------------------------------------------------------------
# /api/analyze
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=12)
    market: Market
    mode: Mode = Field(
        default="long_term",
        description=(
            "Time-horizon preset. ``intraday`` runs only the technical / "
            "sentiment / risk analysts and skips fundamentals fetches; "
            "``short_term`` adds the macro analyst; ``long_term`` runs all "
            "five and uses the framework's default pillar weighting."
        ),
    )
    portfolio_context: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional caller-supplied context (e.g. existing position size, "
            "avg purchase price). Merged into the run's market context after "
            "ContextBuilder runs, so OVR-O4 / OVR-O5 can see the values."
        ),
    )

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError(
                f"Invalid ticker format: {v!r}. Expected uppercase alphanumeric, "
                f"optionally suffixed by '.NS' or '.BO'."
            )
        return v


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    idempotent_hit: bool = Field(
        description="True if the same ticker+market was submitted today and "
        "we returned the existing run_id rather than starting a new run."
    )
    status: Literal["pending", "running", "interrupted", "complete", "error"]
    mode: Mode = Field(
        default="long_term",
        description="Echo of the run mode so the client doesn't have to remember its request.",
    )
    chart_config: ChartConfig = Field(
        description=(
            "Per-mode chart settings — which Upstox interval the main "
            "chart should render on, optional secondary / context "
            "panels, and how often the client should poll for fresh "
            "data. Returned on the 202 so the UI can paint a chart "
            "skeleton immediately while the LangGraph run is still in "
            "flight."
        ),
    )


# ---------------------------------------------------------------------------
# /api/runs
# ---------------------------------------------------------------------------


RunStatus = Literal["pending", "running", "interrupted", "complete", "error"]


class RunDetail(BaseModel):
    """Shape returned from ``GET /api/runs/{run_id}``.

    Contains everything a UI needs to render a completed analysis: the final
    Decision, all five AnalystReports, the Judgment narrative, both debate
    cases, the deterministic evaluation breakdown, and the full reasoning
    trace. Intermediate fields are typed as ``dict`` because they're
    serialized via :func:`apps.api.serializers.serialize_state` so callers
    don't need to import Pydantic models from ``packages.shared``.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ticker: str
    market: Market
    status: RunStatus
    mode: Mode = "long_term"
    chart_config: ChartConfig | None = Field(
        default=None,
        description=(
            "Chart / polling config corresponding to the run's mode. "
            "Returned alongside the analysis so the UI can render the "
            "main chart on the right interval without a second lookup."
        ),
    )
    created_at: datetime
    completed_at: datetime | None = None

    # All optional because the run may still be in flight.
    decision: dict[str, Any] | None = None
    judgment: dict[str, Any] | None = None
    bull_case: dict[str, Any] | None = None
    bear_case: dict[str, Any] | None = None
    analyst_reports: dict[str, dict[str, Any]] = Field(default_factory=dict)
    evaluation: dict[str, Any] | None = None
    reasoning_trace: list[dict[str, Any]] = Field(default_factory=list)

    error: str | None = None
    interrupt: dict[str, Any] | None = Field(
        default=None,
        description="When status='interrupted', payload from the human-review "
        "interrupt (signal, confidence, prompt).",
    )


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(
        min_length=1,
        max_length=200,
        description=(
            "Reviewer's decision. 'approve' finalizes the STRONG_* signal; "
            "any other value downgrades it to HOLD."
        ),
    )


class ApproveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    final_signal: str | None = None


# ---------------------------------------------------------------------------
# /api/portfolio
# ---------------------------------------------------------------------------


class PortfolioPosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    market: Market
    shares: float = Field(ge=0)
    avg_purchase_price: float | None = Field(default=None, ge=0)
    current_value_usd: float | None = Field(default=None, ge=0)


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    positions: list[PortfolioPosition]
    total_value_usd: float = Field(ge=0)


# ---------------------------------------------------------------------------
# /api/watchlist
# ---------------------------------------------------------------------------


class WatchlistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    market: Market
    added_at: datetime


class WatchlistAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=12)
    market: Market

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError(f"Invalid ticker format: {v!r}.")
        return v


class WatchlistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WatchlistItem]


# ---------------------------------------------------------------------------
# /api/price/{ticker}
# ---------------------------------------------------------------------------


PriceInterval = Literal[
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "1d",
    "1wk",
    "1mo",
]


class PriceBar(BaseModel):
    """Single OHLC candle. Wire-shape used by the frontend chart."""

    model_config = ConfigDict(extra="forbid")

    # Unix-seconds timestamp keeps the JSON tiny and is what
    # `lightweight-charts` accepts as the `time` field directly.
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class PriceQuote(BaseModel):
    """Spot quote returned alongside the OHLC series."""

    model_config = ConfigDict(extra="forbid")

    price: float
    change_pct: float | None = None
    currency: str = "INR"
    timestamp: datetime


class PriceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    market: Market
    interval: PriceInterval
    currency: str = "INR"
    bars: list[PriceBar]
    quote: PriceQuote | None = None
    source: str = Field(
        description="Provider that served this payload (`upstox`, `yahoo`, `synthetic`)."
    )
    stale: bool = Field(
        default=False,
        description="True when only the synthetic fallback was available — UI should warn.",
    )


# ---------------------------------------------------------------------------
# /api/buckets
# ---------------------------------------------------------------------------


class BucketResponse(BaseModel):
    """A single strategy bucket as exposed to clients."""

    model_config = ConfigDict(extra="forbid")

    mode: Mode
    tickers: list[str] = Field(
        default_factory=list,
        description="Display-form symbols (no .NS suffix). Capped at 5.",
    )


class BucketsResponse(BaseModel):
    """All three buckets returned together for the initial dashboard sync."""

    model_config = ConfigDict(extra="forbid")

    buckets: dict[Mode, list[str]] = Field(
        default_factory=dict,
        description="Mode → list of display-form tickers.",
    )


class BucketAddRequest(BaseModel):
    """Append tickers to a bucket. Server clamps the result to MAX_BUCKET_SIZE."""

    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(min_length=1, max_length=20)

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, raw: list[str]) -> list[str]:
        out: list[str] = []
        for t in raw:
            v = t.strip().upper()
            if not v:
                continue
            if not _TICKER_RE.match(v):
                raise ValueError(f"Invalid ticker format: {t!r}")
            out.append(v)
        if not out:
            raise ValueError("At least one ticker required")
        return out


class BucketReplaceRequest(BaseModel):
    """Replace a bucket wholesale. Empty list clears the bucket."""

    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, raw: list[str]) -> list[str]:
        out: list[str] = []
        for t in raw:
            v = t.strip().upper()
            if not v:
                continue
            if not _TICKER_RE.match(v):
                raise ValueError(f"Invalid ticker format: {t!r}")
            out.append(v)
        return out


# ---------------------------------------------------------------------------
# /api/runs/latest
# ---------------------------------------------------------------------------


class LatestRunResponse(BaseModel):
    """Newest known run for a ``(ticker, mode)`` pair, or ``run_id=None``."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    market: Market
    mode: Mode
    run_id: str | None = None
    status: RunStatus | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


ServiceStatus = Literal["ok", "degraded", "down", "not_configured"]


class HealthService(BaseModel):
    status: ServiceStatus
    latency_ms: float | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: ServiceStatus
    services: dict[str, HealthService]
    version: str = "0.1.0"


__all__ = [
    "AnalyzeRequest",
    "AnalyzeResponse",
    "ApproveRequest",
    "ApproveResponse",
    "BucketAddRequest",
    "BucketReplaceRequest",
    "BucketResponse",
    "BucketsResponse",
    "HealthResponse",
    "HealthService",
    "LatestRunResponse",
    "Market",
    "Mode",
    "PortfolioPosition",
    "PortfolioResponse",
    "PriceBar",
    "PriceInterval",
    "PriceQuote",
    "PriceResponse",
    "RunDetail",
    "RunStatus",
    "ServiceStatus",
    "WatchlistAddRequest",
    "WatchlistItem",
    "WatchlistResponse",
]

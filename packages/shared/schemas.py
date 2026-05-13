"""Pydantic models shared across providers, agents, and the API layer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Market = Literal["IN", "US"]
Signal = Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
Pillar = Literal["fundamentals", "technicals", "sentiment", "macro", "risk"]
# Run mode: the spec's three time-horizon presets. Default elsewhere is
# ``long_term`` — that path keeps full-coverage parity with the pre-mode
# behaviour. The canonical ``ModeConfig`` registry lives in
# :mod:`packages.shared.config`; we re-export the literal here so request /
# response models can reference it without importing the dataclass module.
Mode = Literal["intraday", "short_term", "long_term"]


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    market: Market
    price: Decimal
    currency: str
    timestamp: datetime
    change_pct: float | None = None
    volume: int | None = None


class OHLCBar(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    interval: Literal["1m", "5m", "15m", "1h", "1d", "1wk", "1mo"]


class Fundamentals(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    market: Market
    as_of: date
    eps_yoy_pct: float | None = None
    eps_qoq_pct: float | None = None
    eps_misses_consecutive: int | None = None
    revenue_yoy_pct: float | None = None
    revenue_decline_quarters_consecutive: int | None = None
    net_margin_current: float | None = None
    net_margin_2q_ago: float | None = None
    industry_avg_margin: float | None = None
    roe_pct: float | None = None
    roa_pct: float | None = None
    fcf_yield_pct: float | None = None
    fcf_negative_quarters_consecutive: int | None = None
    debt_to_equity: float | None = None
    debt_to_equity_yoy_change: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    interest_coverage_ratio: float | None = None
    pe_ratio: float | None = None
    forward_pe: float | None = None
    sector_pe_avg: float | None = None
    peg_ratio: float | None = None
    ev_ebitda: float | None = None
    industry_ev_ebitda_median: float | None = None
    pb_ratio: float | None = None
    dividend_yield_pct: float | None = None
    payout_ratio_pct: float | None = None
    sector: str | None = None
    extra: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class NewsItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    headline: str
    source: str
    url: str
    published_at: datetime
    sentiment_score: float | None = None
    summary: str | None = None


class ChartConfig(BaseModel):
    """Per-mode chart / candle configuration.

    Drives three things the frontend cannot infer on its own:

      * which Upstox candle interval the main chart should render
        (``primary_interval``);
      * optional secondary / context intervals so the UI can stack
        multi-timeframe panels (e.g. 5-min main + 15-min confirmation
        for intraday);
      * how often the client should poll for fresh quotes
        (``polling_interval_seconds``).

    ``lookback_candles`` is the number of candles to fetch on first
    paint. The ContextBuilder translates it to a calendar-day range
    when calling ``get_ohlc`` (calendar days != trading-day candle
    counts, especially for intraday intervals).

    Interval strings use the Upstox vocabulary (``"5minute"``,
    ``"60minute"``, ``"1day"``, ``"1week"``, ``"1month"``). The
    ContextBuilder maps them to the provider-internal short form
    (``"5m"``, ``"1h"``, ``"1d"``, ``"1wk"``, ``"1mo"``) before
    calling providers, so the OHLCBar.interval Literal stays stable.
    """

    model_config = ConfigDict(frozen=True)

    primary_interval: str = Field(
        description="Main chart interval (Upstox string, e.g. '5minute', '1day', '1week').",
    )
    secondary_interval: str | None = Field(
        default=None,
        description="Optional secondary timeframe used for entry / confirmation.",
    )
    context_interval: str | None = Field(
        default=None,
        description="Optional broader context timeframe (e.g. weekly trend on a daily chart).",
    )
    polling_interval_seconds: int = Field(
        gt=0,
        description="How often the frontend should refresh live data, in seconds.",
    )
    lookback_candles: int = Field(
        gt=0,
        description="Number of candles to fetch on initial load.",
    )


class CorporateAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticker: str
    action_type: Literal["dividend", "split", "buyback", "rights", "bonus", "merger", "spinoff"]
    ex_date: date
    record_date: date | None = None
    details: dict[str, str | float | int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent-layer models (LangGraph state, structured LLM I/O)
# ---------------------------------------------------------------------------


class ParsedQuery(BaseModel):
    """Structured output of the orchestrator's query-parsing LLM call.

    Every control-flow branch downstream depends on these fields, so we never
    accept raw model strings — instructor + Pydantic enforces the shape.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str = Field(
        min_length=1,
        description=(
            "Trading symbol exactly as a market data API expects it. "
            "US: bare symbol (AAPL, MSFT). NSE: suffix .NS (RELIANCE.NS). BSE: .BO."
        ),
    )
    market: Market = Field(description="'US' or 'IN'.")
    intent: Literal["analyze", "compare", "monitor"] = Field(
        default="analyze",
        description="What the user wants done with the ticker.",
    )
    horizon_days: int | None = Field(
        default=None,
        ge=1,
        description="Investment horizon in days, if explicitly mentioned.",
    )
    notes: str | None = Field(
        default=None,
        description="One-sentence clarification of anything unusual in the query.",
    )


class AnalystNarrative(BaseModel):
    """LLM-only output for an analyst.

    The score is **deliberately absent** from this schema: the LLM cannot
    return one because the system attaches a deterministic score from
    ``RuleEvaluator``. This makes the "LLM never decides" contract impossible
    to violate by accident.
    """

    model_config = ConfigDict(frozen=True)

    narrative: str = Field(
        min_length=1,
        description="3-5 sentence prose explaining why the pillar scored where it did.",
    )
    top_signals: list[str] = Field(
        default_factory=list,
        description=(
            "3-6 short bullets capturing the key facts that drove the score. "
            "Each bullet should start with the rule id, e.g. 'FUND-001: EPS YoY +25%, strong_buy tier'."
        ),
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Rule IDs the analyst actually referenced; must align with top_signals.",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Self-rated confidence (0-1). Lower it when many rules in the pillar "
            "were skipped due to missing data."
        ),
    )


class AnalystReport(BaseModel):
    """Final per-pillar report assembled by an analyst node.

    ``score`` is set by the system from ``RuleEvaluator`` output, not by the
    LLM. Narrative-shaped fields come from ``AnalystNarrative``.
    """

    model_config = ConfigDict(frozen=True)

    pillar: Pillar
    score: float = Field(
        ge=0,
        le=100,
        description=(
            "0-100 deterministic pillar score from RuleEvaluator. "
            "NOT produced by the LLM."
        ),
    )
    narrative: str = Field(
        min_length=1,
        description="3-5 sentence human-readable explanation of the score.",
    )
    top_signals: list[str] = Field(
        default_factory=list,
        description="Discrete facts driving the score (one per bullet, prefixed with rule id).",
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Rule IDs and/or RAG chunk IDs referenced (audit trail).",
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="Self-reported confidence (0-1). Reflects data completeness, not score magnitude.",
    )


class ReasoningStep(BaseModel):
    """One row in the orchestrator's audit log (state.reasoning_trace)."""

    model_config = ConfigDict(frozen=True)

    node: str = Field(description="Graph node that emitted this step (parse, judge, etc.).")
    timestamp: datetime
    summary: str
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Node-specific structured detail (parsed_query, scores, override IDs, ...).",
    )
    duration_ms: float | None = Field(
        default=None,
        ge=0,
        description="Wall time spent in this node, milliseconds.",
    )


class BullCase(BaseModel):
    """Bull-side debate output. <=200 words enforced by char limit on thesis."""

    model_config = ConfigDict(frozen=True)

    thesis: str = Field(
        min_length=1,
        max_length=1500,  # ~200 English words
        description="3-5 sentence prose argument for the LONG case. Hard 200-word limit.",
    )
    key_supports: list[str] = Field(
        default_factory=list,
        description=(
            "3-5 bullets, each citing a specific pillar score driving the bull case "
            "(e.g. 'Trend pillar 75/100 - golden cross + EMA ribbon aligned')."
        ),
    )
    confidence: float = Field(
        ge=0,
        le=1,
        description="0-1 self-rating of how strong the long case is given the data.",
    )


class BearCase(BaseModel):
    """Bear-side debate output. Symmetric to BullCase."""

    model_config = ConfigDict(frozen=True)

    thesis: str = Field(
        min_length=1,
        max_length=1500,
        description="3-5 sentence prose argument for the SHORT/AVOID case. Hard 200-word limit.",
    )
    key_supports: list[str] = Field(
        default_factory=list,
        description="3-5 bullets, each citing a specific pillar score driving the bear case.",
    )
    confidence: float = Field(ge=0, le=1)


class Judgment(BaseModel):
    """Strategy Judge synthesis output.

    Score and signal here are deterministic copies of ``RuleEvaluator``
    outputs — the LLM only writes ``narrative``. When any override with
    ``overrides_score=true`` fires, the synthesis is templated and bypasses
    the LLM entirely.
    """

    model_config = ConfigDict(frozen=True)

    signal: Signal
    composite_score: float = Field(ge=0, le=100)
    overrides_active: list[str] = Field(
        default_factory=list,
        description="IDs of override rules currently triggered (e.g. 'OVR-O1').",
    )
    bull_case_summary: str = Field(
        default="",
        description="One-sentence acknowledgment of the bull case.",
    )
    bear_case_summary: str = Field(
        default="",
        description="One-sentence acknowledgment of the bear case.",
    )
    cited_rule_ids: list[str] = Field(
        default_factory=list,
        description="Rule IDs surfaced by RAG retrieval that informed the synthesis.",
    )
    narrative: str = Field(
        min_length=1,
        description="4-7 sentence synthesis prose; LLM-authored unless an override fires.",
    )


class JudgeNarrative(BaseModel):
    """LLM-only output for the judge. No score / signal field — those are
    deterministic and attached by the system."""

    model_config = ConfigDict(frozen=True)

    narrative: str = Field(min_length=1)
    bull_case_summary: str = Field(default="")
    bear_case_summary: str = Field(default="")


class Decision(BaseModel):
    """Final actionable verdict — what the user / API layer consumes.

    Position sizing is deterministic from the signal (the LLM is never asked
    to size). ``confidence`` equals the post-override composite score.
    """

    model_config = ConfigDict(frozen=True)

    ticker: str
    market: Market
    signal: Signal
    confidence: float = Field(
        ge=0,
        le=100,
        description="Post-override composite score from RuleEvaluator (0-100).",
    )
    position_size_pct: float = Field(
        ge=0,
        le=10,
        description="Target portfolio % for this ticker; 0-10 per OVR-O5 cap.",
    )
    entry_price: float | None = Field(
        default=None, description="Suggested entry; only set on BUY/STRONG_BUY."
    )
    stop_loss: float | None = Field(
        default=None,
        description="Stop-loss price (8% below entry per OVR-O4 spirit) for BUY/STRONG_BUY.",
    )
    target_price: float | None = Field(
        default=None,
        description="Target price; sourced from analyst consensus or +20% default for BUY/STRONG_BUY.",
    )
    rationale: str = Field(
        description="Plain-language explanation; mirrors the judge's synthesis."
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Rule IDs cited (audit trail).",
    )
    overrides_active: list[str] = Field(
        default_factory=list,
        description="IDs of override rules currently triggered.",
    )
    requires_human_review: bool = Field(
        default=False,
        description="True for STRONG_BUY / STRONG_SELL signals; gates final approval.",
    )
    data_coverage_pct: float = Field(
        default=100.0,
        ge=0,
        le=100,
        description=(
            "Percent of in-scope rules that had data and were evaluated. "
            "UI surfaces this as 'Confidence based on X% data coverage'."
        ),
    )
    warning: str | None = Field(
        default=None,
        description=(
            "Plain-language caution shown alongside the signal. Currently set "
            "when data_coverage_pct < 60 (signal made on thin evidence)."
        ),
    )
    mode: Mode = Field(
        default="long_term",
        description=(
            "Run mode used for this decision. Drives which analysts ran, "
            "which pillar weights composed the score, and whether the "
            "Screener fundamentals scrape was skipped. Defaults to "
            "``long_term`` for backward-compatible callers that don't "
            "set the field explicitly."
        ),
    )
    timestamp: datetime

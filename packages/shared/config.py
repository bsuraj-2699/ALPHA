"""Run-mode configuration: intraday / short-term / long-term.

The mode controls three independent things and they have to stay in sync:

  1. Which analyst agents the orchestrator instantiates and routes to.
  2. The category weights ``RuleEvaluator`` uses when computing the
     composite score (so a 0-weight pillar drops out of the composite
     instead of being silently averaged in at neutral).
  3. Whether ``ContextBuilder`` does the slow Screener fundamentals
     scrape (a no-op for intraday / short-term where fundamentals carry
     0 weight anyway).

Encoding all three in one ``ModeConfig`` keeps them honest: anyone who
adds a new mode has to set the active pillars, the weights, and the
fetch policy in one place.

The five user-facing pillars (``technical``, ``sentiment``, ``risk``,
``macro``, ``fundamental``) map onto ``RuleEvaluator``'s eight rule
categories via :data:`PILLAR_TO_CATEGORIES`. The intra-pillar splits
mirror the framework defaults so a long-term run with the default
weights reproduces the original composite formula exactly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from packages.shared.schemas import ChartConfig

Mode = Literal["intraday", "short_term", "long_term"]
ModePillar = Literal["technical", "sentiment", "risk", "macro", "fundamental"]

# Where the canonical rules spec lives. The schedule + per-mode threshold
# blocks added in rules.json v2.0.1 are loaded lazily from this path so
# operators can edit cadences without touching Python code.
_RULES_JSON_PATH = Path(__file__).resolve().parents[1] / "core" / "rules.json"


# Per-mode chart / polling settings. Frontend renders ``primary_interval``
# as the main chart and uses ``polling_interval_seconds`` to throttle
# live refreshes. The ContextBuilder reads ``primary_interval`` +
# ``lookback_candles`` to fetch the right window of candles for TA.
MODE_CHART_CONFIGS: dict[Mode, ChartConfig] = {
    # Intraday: 5-minute main chart. 78 candles ~= one full NSE/NYSE
    # 6.5-hour session. Secondary 15-min for trend confirmation; we
    # don't need a broader context interval — for a one-day horizon,
    # the daily / weekly view would just be noise.
    "intraday": ChartConfig(
        primary_interval="5minute",
        secondary_interval="15minute",
        context_interval=None,
        polling_interval_seconds=300,
        lookback_candles=78,
    ),
    # Short-term: daily main chart, 90 bars ~= 3 months. 60-minute
    # secondary for staging entries, weekly context for the
    # higher-timeframe trend.
    "short_term": ChartConfig(
        primary_interval="1day",
        secondary_interval="60minute",
        context_interval="1week",
        polling_interval_seconds=3600,
        lookback_candles=90,
    ),
    # Long-term: weekly main chart, 104 bars ~= 2 years. Monthly
    # secondary for the major trend, daily context for staggered
    # buys / sells inside the weekly structure.
    "long_term": ChartConfig(
        primary_interval="1week",
        secondary_interval="1month",
        context_interval="1day",
        polling_interval_seconds=86400,
        lookback_candles=104,
    ),
}


# Map Upstox interval strings to the provider-internal short form
# (``OHLCInterval`` / ``OHLCBar.interval`` literal). Both Upstox and
# Yahoo providers normalise on the short form internally; we translate
# at the ContextBuilder boundary so ChartConfig stays user-facing.
UPSTOX_TO_PROVIDER_INTERVAL: dict[str, str] = {
    "1minute":  "1m",
    "5minute":  "5m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "1h",
    "1day":     "1d",
    "1week":    "1wk",
    "1month":   "1mo",
}


# Approximate trading sessions per calendar day for each interval.
# Used by ``lookback_days_for_chart`` to convert a "I want N candles"
# spec into a calendar-day fetch window. Numbers reflect a 6.5-hour
# US / Indian equity session (~390 minutes); intraday providers occasionally
# return slightly fewer bars on holidays — the +buffer in the helper
# below absorbs that without re-fetching.
_CANDLES_PER_TRADING_DAY: dict[str, float] = {
    "1minute":   390.0,
    "5minute":   78.0,
    "15minute":  26.0,
    "30minute":  13.0,
    "60minute":  6.5,
    "1day":      1.0,
    "1week":     1.0 / 5.0,    # 5 trading days per week
    "1month":    1.0 / 21.0,   # ~21 trading days per month
}


def lookback_days_for_chart(chart: ChartConfig) -> int:
    """Calendar-day window large enough to satisfy ``lookback_candles``.

    Trading sessions skip weekends and holidays, so we inflate the raw
    estimate. The minimums also matter for short intervals — fetching
    "78 5-minute bars" still needs to span a few calendar days when
    the request lands on a Monday morning before the market opens.
    """
    interval = chart.primary_interval
    n = chart.lookback_candles
    per_day = _CANDLES_PER_TRADING_DAY.get(interval)
    if per_day is None:
        # Unknown interval — be generous so providers don't return empty.
        return max(n, 30)
    if interval == "1day":
        # 5 trading days per 7 calendar days, plus a 14-day buffer for
        # holidays and so MA-200 callers (which read further back via
        # ``timedelta(days=400)`` already) never see a short series.
        return int(n * 7 / 5) + 14
    if interval in ("1week", "1month"):
        # Weeklies / monthlies fetch over many calendar days regardless
        # of how many candles we want; stay safely above the requirement.
        days_per_candle = 7 if interval == "1week" else 31
        return n * days_per_candle + 14
    # Intraday: candles_per_trading_day is high, so n / per_day is small.
    # Inflate by 7/5 (calendar / trading days) and floor at 3 to handle
    # weekend boundaries.
    trading_days = max(1.0, n / per_day)
    return max(3, int(trading_days * 7 / 5) + 2)


# How each user-facing pillar splits across RuleEvaluator's rule categories.
# The intra-pillar ratios match the original framework weights so a
# long-term ``ModeConfig`` reproduces ``RuleEvaluator.CATEGORY_WEIGHTS``.
#
#   technical 0.20 = trend 0.125 + momentum 0.075   -> 0.625 / 0.375
#   sentiment 0.33 = sentiment 0.15 + valuation 0.18 -> 0.4545 / 0.5455
#   fundamental 0.25 = fundamentals 0.125 + balance_sheet 0.125 -> 0.5 / 0.5
#
# ``macro`` and ``risk`` are single-category pillars, so the ratio is 1.0.
PILLAR_TO_CATEGORIES: dict[ModePillar, dict[str, float]] = {
    "technical":   {"trend": 0.625, "momentum": 0.375},
    "sentiment":   {"sentiment": 15.0 / 33.0, "valuation": 18.0 / 33.0},
    "fundamental": {"fundamentals": 0.5, "balance_sheet": 0.5},
    "macro":       {"macro": 1.0},
    "risk":        {"risk": 1.0},
}


@dataclass(frozen=True)
class ModeConfig:
    """Per-mode behaviour bundle.

    Attributes
    ----------
    mode
        The mode tag (``intraday`` / ``short_term`` / ``long_term``).
    active_pillars
        Pillars whose analyst nodes the orchestrator should run. The
        orchestrator's conditional edges read this set; pillars not in
        it are skipped entirely (no LLM call, no state writeback).
    pillar_weights
        Composite weight per pillar. Must sum to 1.0 across pillars
        with non-zero weight. Pillars set to 0.0 contribute nothing to
        the composite even if their analyst happens to run.
    skip_screener
        When True, ``ContextBuilder._fundamentals_block`` short-circuits
        the Screener HTML scrape (the slowest provider). Set on modes
        where fundamentals carry 0 weight so we don't pay the latency
        for data we won't score.
    """

    mode: Mode
    active_pillars: frozenset[ModePillar]
    pillar_weights: dict[ModePillar, float] = field(default_factory=dict)
    skip_screener: bool = False
    chart_config: ChartConfig | None = None

    def category_weights(self) -> dict[str, float]:
        """Project ``pillar_weights`` onto RuleEvaluator's 8 categories.

        Each pillar's weight is split across its underlying categories
        using the framework ratios in :data:`PILLAR_TO_CATEGORIES`. A
        pillar with weight 0 contributes 0 to all of its categories,
        which lets ``RuleEvaluator._composite_score`` drop those rules
        from the denominator (it skips weights ``<= 0``).
        """
        out: dict[str, float] = {}
        for pillar, w in self.pillar_weights.items():
            for category, ratio in PILLAR_TO_CATEGORIES[pillar].items():
                out[category] = out.get(category, 0.0) + w * ratio
        return out


# Mode registry. Weights match the spec exactly; intra-pillar splits use
# the framework defaults so long-term + default RuleEvaluator weights
# stay byte-identical to the pre-mode behaviour.
_MODE_CONFIGS: dict[Mode, ModeConfig] = {
    "intraday": ModeConfig(
        mode="intraday",
        active_pillars=frozenset({"technical", "sentiment", "risk"}),
        pillar_weights={
            "technical":   0.40,
            "sentiment":   0.30,
            "risk":        0.30,
            "macro":       0.0,
            "fundamental": 0.0,
        },
        skip_screener=True,
        chart_config=MODE_CHART_CONFIGS["intraday"],
    ),
    "short_term": ModeConfig(
        mode="short_term",
        active_pillars=frozenset({"technical", "sentiment", "risk", "macro"}),
        pillar_weights={
            "technical":   0.35,
            "sentiment":   0.20,
            "risk":        0.20,
            "macro":       0.25,
            "fundamental": 0.0,
        },
        skip_screener=True,
        chart_config=MODE_CHART_CONFIGS["short_term"],
    ),
    "long_term": ModeConfig(
        mode="long_term",
        active_pillars=frozenset(
            {"technical", "sentiment", "risk", "macro", "fundamental"}
        ),
        pillar_weights={
            "technical":   0.15,
            "sentiment":   0.10,
            "risk":        0.15,
            "macro":       0.20,
            "fundamental": 0.40,
        },
        skip_screener=False,
        chart_config=MODE_CHART_CONFIGS["long_term"],
    ),
}


# Map ModePillar -> the analyst Pillar key used in AgentState / Orchestrator.
# ``Pillar`` (in schemas) speaks "fundamentals" / "technicals"; ``ModePillar``
# is the singular shorthand the spec uses ("fundamental", "technical"). They
# need to round-trip cleanly so the orchestrator can pick analyst nodes.
MODE_PILLAR_TO_ANALYST_PILLAR: dict[ModePillar, str] = {
    "fundamental": "fundamentals",
    "technical":   "technicals",
    "sentiment":   "sentiment",
    "macro":       "macro",
    "risk":        "risk",
}

ANALYST_PILLAR_TO_MODE_PILLAR: dict[str, ModePillar] = {
    v: k for k, v in MODE_PILLAR_TO_ANALYST_PILLAR.items()
}


def get_mode_config(mode: Mode) -> ModeConfig:
    """Return the registered :class:`ModeConfig` for ``mode``.

    Raises
    ------
    ValueError
        When ``mode`` isn't one of the three known modes — a defensive
        guard for callers that thread arbitrary strings through (e.g.
        an old API client predating the field).
    """
    cfg = _MODE_CONFIGS.get(mode)
    if cfg is None:
        raise ValueError(
            f"Unknown mode {mode!r}; expected one of {sorted(_MODE_CONFIGS)}"
        )
    return cfg


# ---------------------------------------------------------------------------
# rules.json overlay (schedule + per-mode thresholds)
# ---------------------------------------------------------------------------

# Cached spec — the rules JSON is ~1700 lines, so we read it once per
# process rather than on every scheduler tick. Tests can clear the cache
# via ``_reset_rules_cache`` after monkey-patching the path.
_rules_spec_cache: dict[str, Any] | None = None


def _load_rules_spec() -> dict[str, Any]:
    """Read ``rules.json`` once and cache the parsed dict.

    The schedule loader and the per-mode threshold accessor both go
    through this so we read/parse the file at most once per process.
    """
    global _rules_spec_cache
    if _rules_spec_cache is None:
        try:
            with _RULES_JSON_PATH.open("r", encoding="utf-8") as f:
                _rules_spec_cache = json.load(f)
        except (OSError, ValueError):
            # Tests in some sandboxes don't ship the JSON; degrade to an
            # empty spec so callers fall back to their hard-coded defaults.
            _rules_spec_cache = {}
    return _rules_spec_cache


def _reset_rules_cache() -> None:
    """Drop the cached spec — useful after a test patches the JSON path."""
    global _rules_spec_cache
    _rules_spec_cache = None


@dataclass(frozen=True)
class ModeSchedule:
    """Subset of ``rules.json`` mode.schedule that the API scheduler reads.

    ``type``
        Either ``"interval_during_market_hours"`` (intraday) or
        ``"daily_at"`` (short_term / long_term). Other values cause the
        scheduler to skip that mode.
    ``interval_seconds``
        Cadence for ``interval_during_market_hours``. Ignored otherwise.
    ``time_hhmm``
        ``"HH:MM"`` wall clock for ``daily_at``. Ignored otherwise.
    ``timezone``
        IANA tz name. Defaults to ``"Asia/Kolkata"`` for the IN market.
    ``weekdays``
        ``"Mon-Fri"`` (only weekday string we support today). The
        scheduler treats anything else as "every day".
    ``market``
        Market the schedule belongs to. Always ``"IN"`` today.
    """

    type: str
    interval_seconds: int | None = None
    time_hhmm: str | None = None
    timezone: str = "Asia/Kolkata"
    weekdays: str = "Mon-Fri"
    market: str = "IN"


# Hard-coded fallbacks used when ``rules.json`` is missing or doesn't
# carry a schedule for a mode. Match the values declared in v2.0.1 so
# behaviour is identical between "JSON present" and "JSON absent".
_DEFAULT_SCHEDULES: dict[Mode, ModeSchedule] = {
    "intraday": ModeSchedule(
        type="interval_during_market_hours",
        interval_seconds=300,
        market="IN",
        weekdays="Mon-Fri",
    ),
    "short_term": ModeSchedule(
        type="daily_at",
        time_hhmm="10:00",
        timezone="Asia/Kolkata",
        weekdays="Mon-Fri",
        market="IN",
    ),
    "long_term": ModeSchedule(
        type="daily_at",
        time_hhmm="10:00",
        timezone="Asia/Kolkata",
        weekdays="Mon-Fri",
        market="IN",
    ),
}


def get_mode_schedule(mode: Mode) -> ModeSchedule:
    """Return the schedule for ``mode``, preferring rules.json.

    Order of resolution:
      1. ``modes[mode].schedule`` from ``rules.json`` (if present + valid).
      2. The hard-coded fallback in :data:`_DEFAULT_SCHEDULES`.

    A schedule is "valid" when ``type`` is one of
    ``interval_during_market_hours`` / ``daily_at`` and the type-specific
    field (``interval_seconds`` / ``time``) is set. Malformed entries log
    nothing — they just degrade to the default — because the scheduler
    boots in the API lifespan and we do not want a typo in the spec to
    keep the whole API offline.
    """
    spec = _load_rules_spec()
    raw = ((spec.get("modes") or {}).get(mode) or {}).get("schedule")
    if isinstance(raw, dict):
        kind = raw.get("type")
        if kind == "interval_during_market_hours":
            interval = raw.get("interval_seconds")
            if isinstance(interval, int) and interval > 0:
                return ModeSchedule(
                    type=kind,
                    interval_seconds=interval,
                    market=str(raw.get("market", "IN")),
                    weekdays=str(raw.get("weekdays", "Mon-Fri")),
                    timezone=str(raw.get("timezone", "Asia/Kolkata")),
                )
        elif kind == "daily_at":
            time_str = raw.get("time")
            if isinstance(time_str, str) and ":" in time_str:
                return ModeSchedule(
                    type=kind,
                    time_hhmm=time_str,
                    timezone=str(raw.get("timezone", "Asia/Kolkata")),
                    weekdays=str(raw.get("weekdays", "Mon-Fri")),
                    market=str(raw.get("market", "IN")),
                )
    return _DEFAULT_SCHEDULES[mode]


def get_mode_thresholds(mode: Mode) -> list[dict[str, Any]] | None:
    """Return per-mode thresholds from ``rules.json`` if defined.

    The signal mapper in :class:`packages.core.rule_evaluator.RuleEvaluator`
    falls back to the universal top-level ``thresholds`` block when this
    returns ``None``. That preserves the legacy single-threshold behaviour
    for any mode that does not customise its bands.
    """
    spec = _load_rules_spec()
    raw = ((spec.get("modes") or {}).get(mode) or {}).get("thresholds")
    if isinstance(raw, list) and raw:
        return raw
    return None


DEFAULT_MODE: Mode = "long_term"


__all__ = [
    "ANALYST_PILLAR_TO_MODE_PILLAR",
    "DEFAULT_MODE",
    "MODE_CHART_CONFIGS",
    "MODE_PILLAR_TO_ANALYST_PILLAR",
    "Mode",
    "ModeConfig",
    "ModePillar",
    "ModeSchedule",
    "PILLAR_TO_CATEGORIES",
    "UPSTOX_TO_PROVIDER_INTERVAL",
    "get_mode_config",
    "get_mode_schedule",
    "get_mode_thresholds",
    "lookback_days_for_chart",
]

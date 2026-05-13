"""Backtest runner.

Wires together:

    HistoricalContextBuilder   ->  per-day context dicts
    Orchestrator (offline)     ->  per-day Decision (LLM-free templated narratives)
    PortfolioSimulator         ->  per-day mark-to-market + decision execution
    Benchmarks + Metrics       ->  comparison curves + summary stats

The runner is callable as both:

    * a Python API (``BacktestRunner(...).run(...)``)
    * a CLI (``python -m eval.backtest --tickers ...``)

Decision cadence
----------------
We don't want to fire the orchestrator on every single trading day -
that would be wasteful when the rule evaluator is mostly looking at
slow-moving signals (50/200 SMA, 14-day RSI, 3-month relative strength).
Default cadence is **weekly** - a fresh decision every 5 trading days.
This is configurable via ``decision_cadence_days``.

Robustness
----------
Anything that can blow up (bad bar, missing index data, orchestrator
exception) is logged and skipped — the simulator carries on with
whatever positions it already had. The whole point of the backtest is
to be runnable end-to-end on partial data.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterator

import pandas as pd

from eval.benchmarks import (
    BenchmarkResult,
    equal_weight_buy_and_hold,
    index_buy_and_hold,
)
from eval.historical_context import (
    INDEX_SYMBOL,
    HistoricalContextBuilder,
    HistoricalFrames,
    NoopBuilder,
    fetch_history,
)
from eval.metrics import PerformanceSummary, summarise
from eval.portfolio import (
    DecisionLog,
    EquityPoint,
    PortfolioSimulator,
    Trade,
)
from packages.agents.llm_provider import llm_env_stripped_offline
from packages.agents.orchestrator import Orchestrator
from packages.shared.schemas import Decision, Market

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration / result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestSpec:
    ticker: str
    market: Market
    start_date: date
    end_date: date


@dataclass
class BacktestConfig:
    starting_capital: float = 1_000_000.0
    decision_cadence_days: int = 5
    risk_free_rate: float = 0.0
    # If True, frames are fetched at runner construction; pass False
    # when injecting frames in tests.
    fetch_frames: bool = True


@dataclass
class BacktestResult:
    config: BacktestConfig
    specs: list[BacktestSpec]

    # Strategy curve + trades + decision log
    equity_curve: list[EquityPoint] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    decision_log: list[DecisionLog] = field(default_factory=list)
    summary: PerformanceSummary | None = None

    # Benchmarks (curves identical in shape to ``equity_curve``)
    benchmark_basket: BenchmarkResult | None = None
    benchmark_index: BenchmarkResult | None = None

    # Cached so the report can render OHLC and labels alongside
    frames: dict[str, HistoricalFrames] = field(default_factory=dict)

    # Per-spec decision counts so the report can show "we ran N evals"
    decisions_emitted: int = 0
    decisions_skipped: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _force_offline_llm() -> Iterator[None]:
    """Temporarily strip all known LLM API keys so every agent uses its
    templated fallback. Restore on exit."""
    with llm_env_stripped_offline():
        yield


def _bar_dict(row: pd.Series) -> dict[str, float]:
    return {
        "open": float(row["Open"]),
        "high": float(row["High"]),
        "low": float(row["Low"]),
        "close": float(row["Close"]),
    }


def _frame_to_close_map(df: pd.DataFrame | None) -> dict[date, float]:
    if df is None or df.empty:
        return {}
    return {idx.date(): float(row["Close"]) for idx, row in df.iterrows()}


def _trading_days_for(spec: BacktestSpec, frames: HistoricalFrames) -> list[date]:
    df = frames.get(spec.ticker)
    if df is None or df.empty:
        return []
    in_window = df.loc[
        (df.index >= pd.Timestamp(spec.start_date))
        & (df.index <= pd.Timestamp(spec.end_date))
    ]
    return [d.date() for d in in_window.index]


def _bar_for(spec: BacktestSpec, frames: HistoricalFrames, day: date) -> dict[str, float] | None:
    df = frames.get(spec.ticker)
    if df is None or df.empty:
        return None
    ts = pd.Timestamp(day)
    if ts not in df.index:
        return None
    return _bar_dict(df.loc[ts])


# ---------------------------------------------------------------------------
# BacktestRunner
# ---------------------------------------------------------------------------


class BacktestRunner:
    """Runs the full backtest end-to-end.

    A single runner can handle multiple ``(ticker, market, start, end)``
    specs against one shared portfolio. Frames are fetched up-front so
    the per-day decision loop doesn't touch the network.
    """

    def __init__(
        self,
        specs: list[BacktestSpec],
        config: BacktestConfig | None = None,
        *,
        orchestrator: Orchestrator | None = None,
        frames: dict[str, HistoricalFrames] | None = None,
    ) -> None:
        if not specs:
            raise ValueError("At least one BacktestSpec is required")
        self.specs = list(specs)
        self.config = config or BacktestConfig()

        # NoopBuilder + offline LLMs = zero external calls during the run.
        self._orchestrator = orchestrator or Orchestrator(
            context_builder=NoopBuilder(),
            auto_approve_strong_signals=True,
        )

        if frames is not None:
            self._frames = frames
        elif self.config.fetch_frames:
            self._frames = self._fetch_all_frames()
        else:
            self._frames = {}

    # ----------------------------------------------------------- frames

    def _fetch_all_frames(self) -> dict[str, HistoricalFrames]:
        out: dict[str, HistoricalFrames] = {}
        for spec in self.specs:
            logger.info(
                "Fetching frames for %s (%s) %s -> %s",
                spec.ticker, spec.market, spec.start_date, spec.end_date,
            )
            out[spec.ticker] = fetch_history(
                spec.ticker, spec.market, spec.start_date, spec.end_date
            )
        return out

    # ------------------------------------------------------------- public

    async def run_async(self) -> BacktestResult:
        sim = PortfolioSimulator(
            starting_capital=self.config.starting_capital,
            currency="USD",  # display only; real currency is per-position
        )
        decisions_emitted = 0
        decisions_skipped = 0

        # Build a unified day -> [(spec, bar)] schedule across all tickers.
        spec_days: dict[date, list[BacktestSpec]] = {}
        for spec in self.specs:
            for d in _trading_days_for(spec, self._frames[spec.ticker]):
                spec_days.setdefault(d, []).append(spec)
        days = sorted(spec_days.keys())

        # Per-spec decision-day tracker so cadence can be enforced cheaply
        last_decision_day: dict[str, date | None] = {s.ticker: None for s in self.specs}

        with _force_offline_llm():
            for day in days:
                # 1) Mark-to-market for ALL open positions using today's bars
                today_bars: dict[str, dict[str, float]] = {}
                for ticker, hf in self._frames.items():
                    bar = _bar_for(
                        BacktestSpec(ticker, "US", day, day),  # market unused
                        hf,
                        day,
                    )
                    if bar:
                        today_bars[ticker] = bar
                sim.mark_to_market(day, today_bars)

                # 2) For each spec on this day, maybe run the orchestrator
                for spec in spec_days[day]:
                    last_day = last_decision_day[spec.ticker]
                    cadence = self.config.decision_cadence_days
                    days_since = (day - last_day).days if last_day else cadence
                    if days_since < cadence:
                        continue

                    decision = await self._decide(spec, day)
                    last_decision_day[spec.ticker] = day
                    if decision is None:
                        decisions_skipped += 1
                        continue
                    decisions_emitted += 1

                    bar = today_bars.get(spec.ticker)
                    if bar is None:
                        decisions_skipped += 1
                        continue

                    sim.on_decision(
                        day=day,
                        ticker=spec.ticker,
                        market=spec.market,
                        decision=decision,
                        current_price=bar["close"],
                    )

            # 3) Close out remaining positions at the very last bar
            if days:
                final_day = days[-1]
                final_bars: dict[str, dict[str, float]] = {}
                for ticker, hf in self._frames.items():
                    df = hf.get(ticker)
                    if df is None or df.empty:
                        continue
                    last_row = df.loc[df.index <= pd.Timestamp(final_day)]
                    if last_row.empty:
                        continue
                    final_bars[ticker] = _bar_dict(last_row.iloc[-1])
                sim.close_remaining(final_day, final_bars)

        # 4) Build benchmarks
        bench_basket = equal_weight_buy_and_hold(
            tickers=[s.ticker for s in self.specs],
            closes_by_ticker={
                s.ticker: _frame_to_close_map(self._frames[s.ticker].get(s.ticker))
                for s in self.specs
            },
            starting_capital=self.config.starting_capital,
        )
        # All specs same market for now; in mixed runs we just pick the
        # majority market for the index benchmark and note it.
        majority_market: Market = self.specs[0].market
        index_sym = INDEX_SYMBOL[majority_market]
        index_frames = self._frames[self.specs[0].ticker]
        index_closes = _frame_to_close_map(index_frames.get(index_sym))
        bench_index = index_buy_and_hold(
            market=majority_market,
            index_closes=index_closes,
            starting_capital=self.config.starting_capital,
            label=f"index_{index_sym}",
        )

        summary = summarise(
            sim.equity_curve,
            sim.trades,
            risk_free_rate=self.config.risk_free_rate,
        )

        return BacktestResult(
            config=self.config,
            specs=self.specs,
            equity_curve=sim.equity_curve,
            trades=sim.trades,
            decision_log=sim.decision_log,
            summary=summary,
            benchmark_basket=bench_basket,
            benchmark_index=bench_index,
            frames=self._frames,
            decisions_emitted=decisions_emitted,
            decisions_skipped=decisions_skipped,
        )

    def run(self) -> BacktestResult:
        return asyncio.run(self.run_async())

    # ----------------------------------------------------------- internals

    async def _decide(self, spec: BacktestSpec, day: date) -> Decision | None:
        """Build context, run the orchestrator, return Decision or None on error."""
        builder = HistoricalContextBuilder(self._frames[spec.ticker])
        ctx = builder.build_for_date(spec.ticker, spec.market, day)
        if not ctx or "current_price" not in ctx:
            return None
        try:
            state = await self._orchestrator.arun(
                query=f"Analyze {spec.ticker}",
                ticker=spec.ticker,
                market=spec.market,
                context_overrides=ctx,
            )
        except Exception as e:
            logger.warning(
                "orchestrator failed for %s @ %s: %s", spec.ticker, day, e
            )
            return None

        decision: Any = state.get("decision") if isinstance(state, dict) else None
        if isinstance(decision, Decision):
            return decision
        # The state dict from arun typically contains the Pydantic Decision
        # instance directly (state is an AgentState TypedDict). Belt-and-
        # braces: if a serialized dict snuck in, recover.
        if isinstance(decision, dict):
            try:
                return Decision.model_validate(decision)
            except Exception:
                return None
        return None


__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BacktestRunner",
    "BacktestSpec",
]

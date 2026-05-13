"""Benchmarks for the backtest report.

Two simple, deterministic comparators:

  1. **Equal-weight buy-and-hold of the same tickers** - on day 0, divide
     starting capital across the tested tickers; never trade again.
     Answers "did the agent beat the naive buyer who shopped the same
     basket?".

  2. **Index buy-and-hold** - put 100% into the NIFTY 50 ETF (NIFTYBEES)
     on day 0. Answers "did this beat the index?".

Both produce an :class:`~eval.portfolio.EquityPoint` series identical in
shape to the strategy curve so the same metrics + report renderer work
across all three.

Note: these benchmarks consume already-fetched OHLC data (a
``ticker -> list[bar_dict]`` map keyed by date). They never touch the
network themselves, which is what makes them deterministic in tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from eval.portfolio import EquityPoint
from packages.shared.schemas import Market


# India-only deployment: NIFTYBEES (NIFTY 50 ETF) is the sole benchmark.
INDEX_SYMBOL: dict[Market, str] = {"IN": "NIFTYBEES"}


@dataclass
class BenchmarkResult:
    name: str
    equity_curve: list[EquityPoint] = field(default_factory=list)
    notes: str = ""


def _trading_days(prices: dict[str, dict[date, float]]) -> list[date]:
    """Union of all trading days across all tickers, sorted ascending."""
    seen: set[date] = set()
    for series in prices.values():
        seen.update(series.keys())
    return sorted(seen)


def equal_weight_buy_and_hold(
    tickers: list[str],
    closes_by_ticker: dict[str, dict[date, float]],
    starting_capital: float = 1_000_000.0,
) -> BenchmarkResult:
    """Equal-weight buy-and-hold across the supplied tickers.

    On the first day where ALL tickers have a quote, we allocate
    ``starting_capital / N`` to each and never rebalance. Tickers that
    only quote later are dropped (we don't want sparse-fill artifacts).
    """
    if not tickers:
        return BenchmarkResult(name="equal_weight_buy_and_hold", notes="No tickers")

    days = _trading_days(closes_by_ticker)
    if not days:
        return BenchmarkResult(
            name="equal_weight_buy_and_hold", notes="No price data"
        )

    # First day where every ticker has a price
    initial_day: date | None = None
    initial_prices: dict[str, float] = {}
    for d in days:
        if all(d in closes_by_ticker.get(t, {}) for t in tickers):
            initial_day = d
            initial_prices = {t: closes_by_ticker[t][d] for t in tickers}
            break
    if initial_day is None:
        return BenchmarkResult(
            name="equal_weight_buy_and_hold",
            notes="No common trading day across all tickers",
        )

    # Per-ticker allocation
    per_ticker = starting_capital / len(tickers)
    shares: dict[str, float] = {}
    cash_after_buys = starting_capital
    for t, price in initial_prices.items():
        if price <= 0:
            shares[t] = 0
            continue
        s = math.floor(per_ticker / price)
        shares[t] = s
        cash_after_buys -= s * price

    curve: list[EquityPoint] = []
    for d in days:
        if d < initial_day:
            continue
        position_value = 0.0
        for t in tickers:
            series = closes_by_ticker.get(t, {})
            price = series.get(d, initial_prices[t])
            position_value += shares[t] * price
        curve.append(
            EquityPoint(
                date=d,
                cash=cash_after_buys,
                positions_value=position_value,
                total=cash_after_buys + position_value,
            )
        )

    return BenchmarkResult(
        name="equal_weight_buy_and_hold",
        equity_curve=curve,
        notes=f"{len(tickers)} ticker(s), {len(curve)} days",
    )


def index_buy_and_hold(
    market: Market,
    index_closes: dict[date, float],
    starting_capital: float = 1_000_000.0,
    *,
    label: str | None = None,
) -> BenchmarkResult:
    """100% into the market's headline index on day 0."""
    if not index_closes:
        return BenchmarkResult(
            name=label or f"index_{INDEX_SYMBOL[market]}",
            notes="No index data",
        )
    days = sorted(index_closes.keys())
    initial_price = index_closes[days[0]]
    if initial_price <= 0:
        return BenchmarkResult(
            name=label or f"index_{INDEX_SYMBOL[market]}",
            notes="Initial price non-positive",
        )

    shares = math.floor(starting_capital / initial_price)
    cash = starting_capital - shares * initial_price

    curve: list[EquityPoint] = []
    for d in days:
        price = index_closes[d]
        position_value = shares * price
        curve.append(
            EquityPoint(
                date=d,
                cash=cash,
                positions_value=position_value,
                total=cash + position_value,
            )
        )
    return BenchmarkResult(
        name=label or f"index_{INDEX_SYMBOL[market]}",
        equity_curve=curve,
        notes=f"{INDEX_SYMBOL[market]} · {len(curve)} days",
    )


__all__ = [
    "BenchmarkResult",
    "INDEX_SYMBOL",
    "equal_weight_buy_and_hold",
    "index_buy_and_hold",
]

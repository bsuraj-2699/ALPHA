"""Performance metrics for backtest results.

All functions are pure - no I/O, no global state - so they can be unit
tested deterministically and called from the report renderer too.

Conventions:

  * **Daily returns** are simple ``(today - yesterday) / yesterday``,
    NOT log-returns. Standard backtest convention.
  * **Sharpe ratio** annualised assumes 252 trading days unless
    overridden. Risk-free rate is annualised; subtract its daily
    equivalent before computing the mean / std.
  * **Max drawdown** is the largest peak-to-trough percentage decline
    on the equity curve. Reported as a positive number (0.18 == 18%).
  * **CAGR** uses calendar days, not trading days, so it lines up with
    common buy-and-hold benchmarks.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

from eval.portfolio import EquityPoint, Trade


# ---------------------------------------------------------------------------
# Equity-curve metrics
# ---------------------------------------------------------------------------


def daily_returns(equity_curve: list[EquityPoint]) -> list[float]:
    """Compute daily simple returns. First day is dropped (no prior value)."""
    returns: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1].total
        cur = equity_curve[i].total
        if prev <= 0:
            returns.append(0.0)
        else:
            returns.append((cur - prev) / prev)
    return returns


def total_return(equity_curve: list[EquityPoint]) -> float:
    """Total return over the whole period as a fraction (0.12 == +12%)."""
    if not equity_curve:
        return 0.0
    start = equity_curve[0].total
    end = equity_curve[-1].total
    if start <= 0:
        return 0.0
    return (end - start) / start


def cagr(equity_curve: list[EquityPoint]) -> float:
    """Compound annual growth rate, by calendar days.

    Returns 0.0 for periods <= 0 days or non-positive starting capital.
    """
    if len(equity_curve) < 2:
        return 0.0
    start_v = equity_curve[0].total
    end_v = equity_curve[-1].total
    if start_v <= 0:
        return 0.0
    days = (equity_curve[-1].date - equity_curve[0].date).days
    if days <= 0:
        return 0.0
    years = days / 365.25
    if years <= 0:
        return 0.0
    return (end_v / start_v) ** (1 / years) - 1


def sharpe_ratio(
    equity_curve: list[EquityPoint],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio.

    ``risk_free_rate`` is annualised (e.g. 0.05 for 5%).
    """
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return 0.0
    rf_daily = risk_free_rate / periods_per_year
    excess = [r - rf_daily for r in rets]
    mean = statistics.fmean(excess)
    sd = statistics.pstdev(excess)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(periods_per_year)


def sortino_ratio(
    equity_curve: list[EquityPoint],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Like Sharpe but using downside deviation only (Sortino)."""
    rets = daily_returns(equity_curve)
    if len(rets) < 2:
        return 0.0
    rf_daily = risk_free_rate / periods_per_year
    excess = [r - rf_daily for r in rets]
    downside = [r for r in excess if r < 0]
    if not downside:
        return float("inf") if statistics.fmean(excess) > 0 else 0.0
    sd = math.sqrt(sum(r * r for r in downside) / len(downside))
    if sd == 0:
        return 0.0
    mean = statistics.fmean(excess)
    return (mean / sd) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[EquityPoint]) -> float:
    """Worst peak-to-trough percentage drop. 0.18 == 18% drawdown."""
    if not equity_curve:
        return 0.0
    peak = -math.inf
    worst = 0.0
    for pt in equity_curve:
        peak = max(peak, pt.total)
        if peak > 0:
            dd = (peak - pt.total) / peak
            worst = max(worst, dd)
    return worst


def max_drawdown_window(equity_curve: list[EquityPoint]) -> tuple[date | None, date | None, float]:
    """Return (peak_date, trough_date, drawdown_fraction).

    Useful for the report's drawdown annotation. Both dates can be ``None``
    if the curve never had a drawdown.
    """
    if not equity_curve:
        return None, None, 0.0
    peak_value = -math.inf
    peak_date: date | None = None
    worst = 0.0
    worst_peak: date | None = None
    worst_trough: date | None = None
    for pt in equity_curve:
        if pt.total > peak_value:
            peak_value = pt.total
            peak_date = pt.date
        if peak_value > 0:
            dd = (peak_value - pt.total) / peak_value
            if dd > worst:
                worst = dd
                worst_peak = peak_date
                worst_trough = pt.date
    return worst_peak, worst_trough, worst


# ---------------------------------------------------------------------------
# Trade-level metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeStats:
    n_trades: int
    n_wins: int
    n_losses: int
    hit_rate: float
    avg_holding_days: float
    avg_win_pct: float
    avg_loss_pct: float
    expectancy_pct: float  # avg per-trade %
    profit_factor: float  # sum(wins) / abs(sum(losses)); inf if no losses
    by_exit_reason: dict[str, int]


def trade_stats(trades: list[Trade]) -> TradeStats:
    if not trades:
        return TradeStats(
            n_trades=0,
            n_wins=0,
            n_losses=0,
            hit_rate=0.0,
            avg_holding_days=0.0,
            avg_win_pct=0.0,
            avg_loss_pct=0.0,
            expectancy_pct=0.0,
            profit_factor=0.0,
            by_exit_reason={},
        )

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    sum_wins = sum(t.pnl for t in wins)
    sum_losses = sum(t.pnl for t in losses)
    pf = sum_wins / abs(sum_losses) if sum_losses != 0 else float("inf") if sum_wins > 0 else 0.0

    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1

    return TradeStats(
        n_trades=len(trades),
        n_wins=len(wins),
        n_losses=len(losses),
        hit_rate=len(wins) / len(trades),
        avg_holding_days=statistics.fmean(t.holding_days for t in trades),
        avg_win_pct=statistics.fmean(t.pnl_pct for t in wins) if wins else 0.0,
        avg_loss_pct=statistics.fmean(t.pnl_pct for t in losses) if losses else 0.0,
        expectancy_pct=statistics.fmean(t.pnl_pct for t in trades),
        profit_factor=pf,
        by_exit_reason=by_reason,
    )


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PerformanceSummary:
    starting_capital: float
    ending_value: float
    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    max_drawdown_peak: date | None
    max_drawdown_trough: date | None
    n_days: int
    trades: TradeStats


def summarise(
    equity_curve: list[EquityPoint],
    trades: list[Trade],
    *,
    risk_free_rate: float = 0.0,
) -> PerformanceSummary:
    if not equity_curve:
        empty_stats = trade_stats([])
        return PerformanceSummary(
            starting_capital=0.0,
            ending_value=0.0,
            total_return=0.0,
            cagr=0.0,
            sharpe=0.0,
            sortino=0.0,
            max_drawdown=0.0,
            max_drawdown_peak=None,
            max_drawdown_trough=None,
            n_days=0,
            trades=empty_stats,
        )

    peak, trough, dd = max_drawdown_window(equity_curve)
    return PerformanceSummary(
        starting_capital=equity_curve[0].total,
        ending_value=equity_curve[-1].total,
        total_return=total_return(equity_curve),
        cagr=cagr(equity_curve),
        sharpe=sharpe_ratio(equity_curve, risk_free_rate),
        sortino=sortino_ratio(equity_curve, risk_free_rate),
        max_drawdown=dd,
        max_drawdown_peak=peak,
        max_drawdown_trough=trough,
        n_days=len(equity_curve),
        trades=trade_stats(trades),
    )


__all__ = [
    "PerformanceSummary",
    "TradeStats",
    "cagr",
    "daily_returns",
    "max_drawdown",
    "max_drawdown_window",
    "sharpe_ratio",
    "sortino_ratio",
    "summarise",
    "total_return",
    "trade_stats",
]

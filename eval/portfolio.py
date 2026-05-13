"""Portfolio simulator.

Consumes :class:`packages.shared.schemas.Decision` objects emitted by the
orchestrator, applies them to a virtual book, and tracks daily mark-to-
market plus per-trade attribution.

Trade lifecycle
---------------
1. **Open**:  on a BUY / STRONG_BUY decision (and no existing position),
   buy ``floor((cash * pct/100) / entry_price)`` shares at ``entry_price``.
   Stop-loss and target prices are recorded on the position.
2. **Hold / mark-to-market**:  every trading day after open, walk the
   day's bar:
     - if ``low <= stop_loss`` -> exit at ``stop_loss``  (loss capped)
     - elif ``high >= target_price`` -> exit at ``target_price``
     - else -> hold; equity contribution = ``shares * close``
3. **Signal exit**:  on a SELL / STRONG_SELL decision against an open
   position, exit at the next day's open (or, lacking that, the current
   close - simulators fudge this either way).

Multi-ticker
------------
The simulator handles any number of tickers concurrently. Cash is shared
across the book: opening a position deducts; closing one credits.
Position sizing is *current-cash-anchored*, not initial-capital-anchored,
so over-leverage isn't possible.

Currency
--------
We don't convert FX. Each market's positions are tracked in their native
currency by attaching ``Market`` to the position; reporting is per-market.
The default starting capital is 1_000_000 in whichever currency the user
labels (``USD`` or ``INR``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from packages.shared.schemas import Decision, Market, Signal


ExitReason = Literal["stop_loss", "target", "signal_exit", "end_of_test"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Position:
    ticker: str
    market: Market
    shares: float
    entry_price: float
    entry_date: date
    stop_loss: float | None
    target_price: float | None
    decision_signal: Signal
    decision_confidence: float
    overrides_active: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)


@dataclass
class Trade:
    ticker: str
    market: Market
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    shares: float
    pnl: float
    pnl_pct: float
    holding_days: int
    exit_reason: ExitReason
    decision_signal: Signal
    decision_confidence: float
    overrides_active: list[str] = field(default_factory=list)


@dataclass
class EquityPoint:
    date: date
    cash: float
    positions_value: float
    total: float


@dataclass
class DecisionLog:
    """Audit trail entry for every decision the simulator received."""

    date: date
    ticker: str
    market: Market
    signal: Signal
    confidence: float
    position_size_pct: float
    entry_price: float | None
    stop_loss: float | None
    target_price: float | None
    overrides_active: list[str] = field(default_factory=list)
    action_taken: Literal["opened", "closed", "skipped_already_open", "skipped_no_position", "skipped_hold", "skipped_no_cash"] = "skipped_hold"
    notes: str = ""


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


@dataclass
class _DayBar:
    open: float
    high: float
    low: float
    close: float


class PortfolioSimulator:
    """Simulates a portfolio against a stream of :class:`Decision` events.

    Workflow:

        sim = PortfolioSimulator(starting_capital=1_000_000)
        for day in trading_days:
            # 1) mark-to-market against today's prices (applies stops/targets)
            sim.mark_to_market(day, bars_for_today)
            # 2) feed today's decisions
            for ticker, decision in todays_decisions.items():
                sim.on_decision(day, ticker, market, decision, bars_for_today[ticker].close)
        sim.close_remaining(last_day, last_bars)
    """

    def __init__(
        self,
        starting_capital: float = 1_000_000.0,
        currency: str = "USD",
    ) -> None:
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        self.starting_capital = starting_capital
        self.currency = currency

        self._cash: float = starting_capital
        self._positions: dict[str, Position] = {}  # keyed by ticker
        self._trades: list[Trade] = []
        self._equity_curve: list[EquityPoint] = []
        self._decision_log: list[DecisionLog] = []

    # ----------------------------------------------------------- accessors

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def trades(self) -> list[Trade]:
        return list(self._trades)

    @property
    def equity_curve(self) -> list[EquityPoint]:
        return list(self._equity_curve)

    @property
    def decision_log(self) -> list[DecisionLog]:
        return list(self._decision_log)

    def equity_total(self, prices: dict[str, float] | None = None) -> float:
        """Total book value at the latest known prices.

        If ``prices`` is omitted we use each open position's entry price
        (i.e. zero unrealised P&L) - useful only for sanity checks.
        """
        prices = prices or {}
        positions_value = 0.0
        for pos in self._positions.values():
            mark = prices.get(pos.ticker, pos.entry_price)
            positions_value += pos.shares * mark
        return self._cash + positions_value

    # ------------------------------------------------------ mark-to-market

    def mark_to_market(
        self,
        day: date,
        bars: dict[str, _DayBar | dict[str, float]],
    ) -> None:
        """Walk each open position against today's OHLC and apply stops/targets.

        ``bars`` may be a dict of ``_DayBar`` *or* a dict of dicts with
        keys ``open / high / low / close`` so callers using pandas /
        yfinance rows don't have to convert.

        Order of resolution within a single bar: stop-loss before target.
        Both being hit on the same bar can't be reasoned about with daily
        data; we conservatively assume the worse outcome (stop-loss).
        """

        positions_value = 0.0
        for ticker, pos in list(self._positions.items()):
            bar = bars.get(ticker)
            if bar is None:
                # No bar for this ticker today (holiday on that exchange,
                # newly-listed, etc.) - hold at entry-price contribution
                # so equity doesn't snap to zero.
                positions_value += pos.shares * pos.entry_price
                continue

            o, h, low, c = _coerce_bar(bar)

            # Stop-loss check FIRST
            if pos.stop_loss is not None and low <= pos.stop_loss:
                self._close_position(
                    pos, exit_price=pos.stop_loss, exit_date=day, reason="stop_loss"
                )
                continue

            # Target check
            if pos.target_price is not None and h >= pos.target_price:
                self._close_position(
                    pos, exit_price=pos.target_price, exit_date=day, reason="target"
                )
                continue

            # Survived the day - mark at close
            positions_value += pos.shares * c
            del o  # unused locally; kept named in _coerce_bar for clarity

        self._equity_curve.append(
            EquityPoint(
                date=day,
                cash=self._cash,
                positions_value=positions_value,
                total=self._cash + positions_value,
            )
        )

    # --------------------------------------------------------- on_decision

    def on_decision(
        self,
        day: date,
        ticker: str,
        market: Market,
        decision: Decision,
        current_price: float,
    ) -> None:
        """Apply one decision. Idempotent within a day per ticker."""

        log_entry = DecisionLog(
            date=day,
            ticker=ticker,
            market=market,
            signal=decision.signal,
            confidence=decision.confidence,
            position_size_pct=decision.position_size_pct,
            entry_price=decision.entry_price,
            stop_loss=decision.stop_loss,
            target_price=decision.target_price,
            overrides_active=list(decision.overrides_active),
        )

        signal = decision.signal
        existing = self._positions.get(ticker)

        if signal in ("BUY", "STRONG_BUY"):
            if existing is not None:
                log_entry.action_taken = "skipped_already_open"
                log_entry.notes = "Position already open — averaging-in disabled in MVP"
                self._decision_log.append(log_entry)
                return

            entry_price = (
                decision.entry_price
                if decision.entry_price and decision.entry_price > 0
                else current_price
            )
            target_pct = decision.position_size_pct / 100.0
            allocation = self._cash * target_pct
            if allocation <= 0 or entry_price <= 0:
                log_entry.action_taken = "skipped_no_cash"
                log_entry.notes = "Allocation zero or non-positive entry price"
                self._decision_log.append(log_entry)
                return

            shares = math.floor(allocation / entry_price)
            if shares <= 0:
                log_entry.action_taken = "skipped_no_cash"
                log_entry.notes = (
                    f"Cash {self._cash:.2f} too small for {entry_price:.2f}@{target_pct:.1%}"
                )
                self._decision_log.append(log_entry)
                return

            cost = shares * entry_price
            if cost > self._cash + 1e-6:
                shares = math.floor(self._cash / entry_price)
                cost = shares * entry_price
                if shares <= 0:
                    log_entry.action_taken = "skipped_no_cash"
                    self._decision_log.append(log_entry)
                    return

            self._cash -= cost
            self._positions[ticker] = Position(
                ticker=ticker,
                market=market,
                shares=shares,
                entry_price=entry_price,
                entry_date=day,
                stop_loss=decision.stop_loss,
                target_price=decision.target_price,
                decision_signal=signal,
                decision_confidence=decision.confidence,
                overrides_active=list(decision.overrides_active),
                citations=list(decision.citations),
            )
            log_entry.action_taken = "opened"
            log_entry.notes = f"shares={shares} cost={cost:.2f}"
            self._decision_log.append(log_entry)
            return

        if signal in ("SELL", "STRONG_SELL"):
            if existing is None:
                log_entry.action_taken = "skipped_no_position"
                log_entry.notes = "Sell signal but no open position"
                self._decision_log.append(log_entry)
                return
            self._close_position(
                existing, exit_price=current_price, exit_date=day, reason="signal_exit"
            )
            log_entry.action_taken = "closed"
            log_entry.notes = f"closed {existing.shares} shares @ {current_price:.2f}"
            self._decision_log.append(log_entry)
            return

        # HOLD / unknown
        log_entry.action_taken = "skipped_hold"
        self._decision_log.append(log_entry)

    # --------------------------------------------------------- finalisation

    def close_remaining(
        self,
        day: date,
        bars: dict[str, _DayBar | dict[str, float]],
    ) -> None:
        """Mark all still-open positions out at the final bar close."""
        for ticker, pos in list(self._positions.items()):
            bar = bars.get(ticker)
            if bar is None:
                # Use entry price as last resort
                self._close_position(
                    pos, exit_price=pos.entry_price, exit_date=day, reason="end_of_test"
                )
                continue
            _, _, _, c = _coerce_bar(bar)
            self._close_position(pos, exit_price=c, exit_date=day, reason="end_of_test")

    # --------------------------------------------------------------- helpers

    def _close_position(
        self,
        pos: Position,
        *,
        exit_price: float,
        exit_date: date,
        reason: ExitReason,
    ) -> None:
        proceeds = pos.shares * exit_price
        self._cash += proceeds

        cost_basis = pos.shares * pos.entry_price
        pnl = proceeds - cost_basis
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price if pos.entry_price else 0.0
        holding_days = (exit_date - pos.entry_date).days

        self._trades.append(
            Trade(
                ticker=pos.ticker,
                market=pos.market,
                entry_date=pos.entry_date,
                exit_date=exit_date,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                shares=pos.shares,
                pnl=pnl,
                pnl_pct=pnl_pct,
                holding_days=holding_days,
                exit_reason=reason,
                decision_signal=pos.decision_signal,
                decision_confidence=pos.decision_confidence,
                overrides_active=list(pos.overrides_active),
            )
        )

        del self._positions[pos.ticker]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_bar(
    bar: _DayBar | dict[str, float],
) -> tuple[float, float, float, float]:
    if isinstance(bar, _DayBar):
        return bar.open, bar.high, bar.low, bar.close
    return (
        float(bar["open"]),
        float(bar["high"]),
        float(bar["low"]),
        float(bar["close"]),
    )


__all__ = [
    "DecisionLog",
    "EquityPoint",
    "ExitReason",
    "PortfolioSimulator",
    "Position",
    "Trade",
]

"""CLI entry point for the backtest.

Usage::

    # Single ticker, full year
    python -m eval.backtest --tickers AAPL --market US \
        --start 2023-01-01 --end 2023-12-31 \
        --output reports/aapl_2023.html

    # Multiple tickers (same market)
    python -m eval.backtest --tickers AAPL,MSFT,NVDA --market US \
        --start 2023-01-01 --end 2023-12-31 \
        --capital 1000000 --cadence 5

    # Indian listing
    python -m eval.backtest --tickers RELIANCE.NS,INFY.NS --market IN \
        --start 2023-01-01 --end 2023-12-31

The CLI never burns LLM tokens (it strips all LLM API keys for the
duration of the run via the runner's ``_force_offline_llm`` context).

If you need to run multi-market in one shot, call the Python API
directly — :class:`eval.runner.BacktestRunner` takes a list of specs
each with their own market.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from eval.reports import write_report
from eval.runner import BacktestConfig, BacktestRunner, BacktestSpec
from packages.shared.schemas import Market


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_market(s: str) -> Market:
    s = s.upper().strip()
    if s not in ("US", "IN"):
        raise argparse.ArgumentTypeError(f"market must be US or IN, got {s!r}")
    return s  # type: ignore[return-value]


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m eval.backtest",
        description="Replay the orchestrator against historical OHLC and produce an HTML report.",
    )
    p.add_argument(
        "--tickers",
        required=True,
        help="Comma-separated list (e.g. 'AAPL' or 'AAPL,MSFT,NVDA').",
    )
    p.add_argument(
        "--market",
        type=_parse_market,
        default="US",
        help="US or IN. All tickers share this market in CLI mode.",
    )
    p.add_argument("--start", type=_parse_date, required=True, help="YYYY-MM-DD")
    p.add_argument("--end", type=_parse_date, required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--capital",
        type=float,
        default=1_000_000.0,
        help="Starting capital (default 1,000,000).",
    )
    p.add_argument(
        "--cadence",
        type=int,
        default=5,
        help="Trading days between decisions per ticker (default 5).",
    )
    p.add_argument(
        "--risk-free-rate",
        type=float,
        default=0.0,
        help="Annualised risk-free rate for Sharpe (e.g. 0.045 = 4.5 percent).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("reports/backtest.html"),
        help="HTML report destination (default: reports/backtest.html).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG-level logs from yfinance / orchestrator.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # yfinance is chatty even at INFO
    logging.getLogger("yfinance").setLevel(logging.WARNING)

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print("error: --tickers required at least one symbol", file=sys.stderr)
        return 2

    if args.start >= args.end:
        print("error: --start must be before --end", file=sys.stderr)
        return 2

    specs = [
        BacktestSpec(
            ticker=t,
            market=args.market,
            start_date=args.start,
            end_date=args.end,
        )
        for t in tickers
    ]

    config = BacktestConfig(
        starting_capital=args.capital,
        decision_cadence_days=args.cadence,
        risk_free_rate=args.risk_free_rate,
    )

    print(
        f"[backtest] {len(specs)} ticker(s) · {args.start} → {args.end} · "
        f"${args.capital:,.0f} starting · cadence {args.cadence}d",
        file=sys.stderr,
    )
    runner = BacktestRunner(specs=specs, config=config)
    result = runner.run()

    out = write_report(result, args.output)
    print(
        f"[backtest] {result.decisions_emitted} decisions, {len(result.trades)} trades, "
        f"final equity ${result.summary.ending_value:,.0f} "
        f"({result.summary.total_return * 100:+.2f}%)"
        if result.summary
        else "[backtest] no summary",
        file=sys.stderr,
    )
    print(f"[backtest] report written to: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

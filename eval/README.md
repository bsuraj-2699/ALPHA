# `eval/` — backtest + scenario harness

Two surfaces, one goal: prove the agent's deterministic core is sound
*before* spending tokens or capital.

| Surface              | What it does                                                                                                                                                                                      | When you run it       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| **Backtest**         | Replays the orchestrator day-by-day against historical OHLC, simulates a portfolio with stops + targets, compares against buy-and-hold benchmarks, and writes a self-contained HTML report.       | manually, from a CLI  |
| **Scenarios**        | A frozen set of hand-labeled `(context, expected_signal)` pairs covering buy / sell / hold / overrides / partial-data edge cases. Catches signal drift the moment a prompt or rule changes.      | every test run, in CI |

Everything in this package runs **offline**. No `ANTHROPIC_API_KEY`
required, no live market-data fetches outside the one-time yfinance
pull at the start of a backtest. That makes results reproducible and
makes CI free.

---

## Backtest

### CLI

```bash
# US tech basket, full year
python -m eval.backtest \
  --tickers AAPL,MSFT,NVDA \
  --market US \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --capital 1000000 \
  --cadence 5 \
  --output reports/2023_us_tech.html

# Indian listing
python -m eval.backtest \
  --tickers RELIANCE.NS,INFY.NS \
  --market IN \
  --start 2023-01-01 \
  --end 2023-12-31 \
  --output reports/2023_in_largecap.html
```

The output is a single `*.html` file: opens in any browser, no JS deps.
It contains:

- **Summary cards**: total return, CAGR, Sharpe, Sortino, max drawdown,
  trade count, hit rate, avg holding period.
- **Equity curve** (SVG, normalised to 100): strategy vs. equal-weight
  buy-and-hold of the same basket vs. buy-and-hold of NIFTYBEES
  (NIFTY 50 ETF, IN-only deployment).
- **Strategy vs benchmarks** table: apples-to-apples comparison of
  return / Sharpe / drawdown.
- **Trades** table: every closed trade with entry/exit/PnL/exit-reason.
- **Decision log** table: every decision the orchestrator emitted plus
  what the simulator did with it.

### Python API

For programmatic use (e.g. you want to feed your own pre-fetched frames
or hand-craft a `(ticker, market, start, end)` mix across markets):

```python
from datetime import date
from eval.runner import BacktestRunner, BacktestSpec, BacktestConfig
from eval.reports import write_report

specs = [
    BacktestSpec("AAPL", "US", date(2023, 1, 1), date(2023, 12, 31)),
    BacktestSpec("RELIANCE.NS", "IN", date(2023, 1, 1), date(2023, 12, 31)),
]
config = BacktestConfig(starting_capital=1_000_000, decision_cadence_days=5)
result = BacktestRunner(specs=specs, config=config).run()
write_report(result, "reports/mixed.html")
```

### How decisions are made

The orchestrator runs in full — same parse → context-build → 5 analysts →
debate → judge → decide pipeline as production. The only differences:

1. **`NoopBuilder`** replaces `ContextBuilder` — no live API calls
   during the loop. Context is fed in via `arun(..., context_overrides=...)`.
2. **`HistoricalContextBuilder`** synthesises that context for each day
   from cached OHLC: technicals via `compute_indicators`, relative
   strength vs. the market index, VIX level, beta. Anything we can't
   derive from price alone (fundamentals, news, macro detail) is left
   absent — the rule evaluator already skips rules with missing data
   and treats them as neutral 50, so the backtest degrades gracefully
   on incomplete history.
3. **`ANTHROPIC_API_KEY` is popped** for the duration of the run, so
   every analyst / judge / debate falls back to its templated narrator.
   Scores are deterministic regardless.

### Decision cadence

By default the runner only fires the orchestrator every 5 trading days
(`--cadence 5`). For slow-moving signals (50/200 SMAs, 14-day RSI,
3-month relative strength) firing every day adds noise without adding
information. Override per run.

### Honest limitations

- **Fundamentals are absent for backtests.** yfinance gives current
  fundamentals only; back-fitting historical EPS / revenue / margins
  per as-of-date is non-trivial. The MVP runs technicals-dominant. To
  bring fundamentals in, plug a historical fundamentals provider into
  `HistoricalContextBuilder.build_for_date` — the rule_evaluator picks
  them up automatically.
- **Macro is mostly empty.** Same shape as fundamentals: FRED could be
  wired through `HistoricalContextBuilder` to populate `policy_rate_trend`
  / `gdp_yoy_pct` / `cpi_yoy_pct`. The MVP leaves macro fields absent.
- **Trade execution is simplified.** Stops/targets resolve at the
  marked level on the day they're touched (we don't model slippage or
  partial fills). When a single bar contains both stop and target, we
  conservatively assume the stop hit first.
- **Cash is shared across markets.** The simulator tracks one cash
  pool; FX conversion is not performed. For pure single-market runs
  this is correct.

---

## Scenarios

15 hand-labeled JSON files under `scenarios/`, plus a runner and a CI
parametrised test that fires the full pipeline on each. See
[`scenarios/README.md`](./scenarios/README.md) for the schema and the
methodology behind the bundled set.

In short:

```
$ pytest eval/tests/test_scenarios.py -v
eval/tests/test_scenarios.py::test_scenario_signal_matches_expected[aapl_2023_q1_earnings_beat] PASSED
eval/tests/test_scenarios.py::test_scenario_signal_matches_expected[nvda_2023_ai_breakout] PASSED
eval/tests/test_scenarios.py::test_scenario_signal_matches_expected[wirecard_fraud_signals] PASSED
...
```

Any rule / prompt / threshold change that pushes a labeled context to
the wrong signal class fails CI immediately, with a diagnostic that
points at the specific scenario and the actual decision.

---

## Layout

```
eval/
├── __init__.py
├── README.md                  # this file
├── backtest.py                # CLI: python -m eval.backtest --tickers ...
├── runner.py                  # BacktestRunner (orchestrator + simulator glue)
├── portfolio.py               # PortfolioSimulator (stops, targets, multi-ticker)
├── metrics.py                 # Sharpe, drawdown, hit rate, etc.
├── benchmarks.py              # equal-weight + index buy-and-hold
├── historical_context.py      # HistoricalContextBuilder + NoopBuilder
├── reports.py                 # self-contained HTML report (SVG)
├── scenarios/
│   ├── README.md              # schema, methodology, how to add more
│   ├── _factory.py            # one-shot generator for the bundled JSONs
│   ├── runner.py              # load + run + validate scenarios
│   └── *.json                 # 15 hand-labeled scenarios
└── tests/
    ├── test_portfolio.py      # PortfolioSimulator unit tests
    ├── test_metrics.py        # metric formula tests
    ├── test_benchmarks.py     # benchmark curve tests
    ├── test_reports.py        # HTML structure tests
    ├── test_runner_smoke.py   # end-to-end runner with synthetic frames
    └── test_scenarios.py      # CI: runs every scenario through the orchestrator
```

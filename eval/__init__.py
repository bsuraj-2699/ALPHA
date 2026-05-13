"""Backtesting + scenario evaluation package.

Two surfaces:

  * :mod:`eval.backtest` / :mod:`eval.runner` - replay the orchestrator
    against historical price data, simulate a portfolio, and emit an HTML
    report. The orchestrator runs offline (no LLM calls; templated fallbacks)
    so a full year of decisions costs nothing.

  * :mod:`eval.scenarios` - a curated set of hand-labeled context dicts
    that pin down expected signals. CI runs every scenario through the
    full pipeline and asserts the signal hasn't drifted - any prompt /
    rule change that regresses one of these is caught at PR time.

Design choices worth knowing about:

  * ``HistoricalContextBuilder`` only fills in what we can derive from
    historical OHLC (technicals, relative strength, VIX, beta). Everything
    fundamental / news-based is left absent on purpose - the rule
    evaluator already skips rules with missing required fields and
    treats them as neutral, so the backtest degrades gracefully on
    incomplete data instead of failing.
  * The orchestrator is invoked with ``context_overrides`` containing the
    historical context, plus a ``NoopBuilder`` that returns ``{}`` so no
    live API calls are made.
"""

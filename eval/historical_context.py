"""Historical context builder for backtests.

Two pieces:

  * :class:`NoopBuilder` - a placeholder for the orchestrator's
    ``context_builder`` argument. Returns ``{}`` so no live API calls
    happen during backtest. The actual context is fed via
    ``arun(..., context_overrides=...)``.

  * :class:`HistoricalContextBuilder` - reproduces a *historical*
    context dict for ``(ticker, market, as_of)`` from cached OHLC.
    Fields it can fill:

        - All technicals (via :func:`packages.data.providers.technicals.compute_indicators`)
        - VIX level / 5d change
        - Beta vs market index
        - Relative strength: 3-month stock / market / sector returns
        - Market regime (bull/bear/sideways) from index trend

    Fields it deliberately leaves absent (rule_evaluator skips those rules
    cleanly with neutral=50 score):

        - Fundamentals (eps_yoy_pct, etc.) - yfinance only exposes the
          *current* snapshot; back-fitting historical fundamentals
          accurately is non-trivial.
        - News / sentiment - GDELT history is incomplete pre-2015 and
          we don't keep a local mirror.
        - Macro (rates, GDP) - could plug FRED later; for an MVP the
          MACRO pillar will mostly score neutral.

The module is sync-friendly (no external API calls inside ``build``);
all yfinance fetches happen up-front in :func:`fetch_history` and the
results are passed in. That makes the builder cheap to call per-day in
the backtest loop and easy to test with mocked frames.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from packages.data.providers.technicals import compute_indicators
from packages.shared.schemas import Market

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Yahoo symbols matching context_builder.MARKET_INDEX
# ---------------------------------------------------------------------------

INDEX_SYMBOL: dict[Market, str] = {"IN": "NIFTYBEES"}
VIX_SYMBOL: dict[Market, str] = {"IN": "^INDIAVIX"}


# ---------------------------------------------------------------------------
# Noop builder (used inside the orchestrator)
# ---------------------------------------------------------------------------


class NoopBuilder:
    """No-op stand-in for ``ContextBuilder`` during backtests.

    The orchestrator's ``_context_build_node`` always calls
    ``builder.build(ticker, market)``. We return ``{}`` so the merge
    inside that node yields ``{**{}, **caller_overrides} == caller_overrides``,
    which is exactly the historical context we seeded via ``arun``.
    """

    async def build(self, ticker: str, market: Market) -> dict[str, Any]:  # noqa: ARG002
        return {}


# ---------------------------------------------------------------------------
# Helpers — relative strength / regime / VIX / beta
# ---------------------------------------------------------------------------


def _three_month_return_pct(closes: pd.Series, as_of: date) -> float | None:
    """Closes is a date-indexed pandas Series of close prices."""
    closes = closes.sort_index()
    upto = closes.loc[: pd.Timestamp(as_of)]
    if len(upto) < 60:  # need ~3 months
        return None
    last = float(upto.iloc[-1])
    # 63 trading days = ~3 months
    n = min(len(upto), 64)
    base = float(upto.iloc[-n])
    if base <= 0:
        return None
    return (last - base) / base * 100.0


def _market_regime(index_closes: pd.Series, as_of: date) -> str | None:
    """Crude bull/bear/sideways classifier:

      * Bull:    index > 200 SMA AND 50 SMA > 200 SMA
      * Bear:    index < 200 SMA AND 50 SMA < 200 SMA
      * else:    sideways
    """
    closes = index_closes.sort_index().loc[: pd.Timestamp(as_of)]
    if len(closes) < 200:
        return None
    sma50 = closes.rolling(50).mean().iloc[-1]
    sma200 = closes.rolling(200).mean().iloc[-1]
    last = closes.iloc[-1]
    if pd.isna(sma50) or pd.isna(sma200):
        return None
    if last > sma200 and sma50 > sma200:
        return "bull"
    if last < sma200 and sma50 < sma200:
        return "bear"
    return "sideways"


def _beta(stock_closes: pd.Series, index_closes: pd.Series, as_of: date) -> float | None:
    """OLS beta of stock daily-returns vs index daily-returns over the
    trailing 1y as-of ``as_of``. Returns ``None`` if not enough data."""
    s = stock_closes.sort_index().loc[: pd.Timestamp(as_of)].tail(252)
    i = index_closes.sort_index().loc[: pd.Timestamp(as_of)].tail(252)
    joined = pd.concat([s, i], axis=1, join="inner").dropna()
    if len(joined) < 60:
        return None
    rs = joined.iloc[:, 0].pct_change().dropna()
    ri = joined.iloc[:, 1].pct_change().dropna()
    aligned = pd.concat([rs, ri], axis=1, join="inner").dropna()
    if len(aligned) < 30:
        return None
    cov = aligned.iloc[:, 0].cov(aligned.iloc[:, 1])
    var = aligned.iloc[:, 1].var()
    if var <= 0 or math.isnan(var):
        return None
    return float(cov / var)


def _vix_block(vix_closes: pd.Series, as_of: date) -> dict[str, Any]:
    closes = vix_closes.sort_index().loc[: pd.Timestamp(as_of)]
    if closes.empty:
        return {}
    out: dict[str, Any] = {"vix_level": float(closes.iloc[-1])}
    if len(closes) >= 6:
        five_back = float(closes.iloc[-6])
        if five_back > 0:
            out["vix_change_5d_pct"] = (closes.iloc[-1] - five_back) / five_back * 100.0
    return out


# ---------------------------------------------------------------------------
# Historical context builder
# ---------------------------------------------------------------------------


@dataclass
class HistoricalFrames:
    """Pre-fetched OHLC frames keyed by symbol.

    Keys we care about:

        - ticker symbol           (e.g. "RELIANCE.NS")
        - INDEX_SYMBOL[market]    (e.g. "NIFTYBEES")
        - VIX_SYMBOL[market]      (e.g. "^INDIAVIX")

    Each value is a date-indexed pandas DataFrame with the canonical
    columns ``Open / High / Low / Close / Volume``.
    """

    frames: dict[str, pd.DataFrame]

    def get(self, symbol: str) -> pd.DataFrame | None:
        return self.frames.get(symbol)


class HistoricalContextBuilder:
    """Constructs a context dict as-of a historical date, from cached frames.

    Usage::

        frames = fetch_history(ticker, market, start, end)
        builder = HistoricalContextBuilder(frames)
        ctx = builder.build_for_date(ticker, market, as_of=trading_day)
    """

    def __init__(self, frames: HistoricalFrames) -> None:
        self.frames = frames

    def build_for_date(
        self,
        ticker: str,
        market: Market,
        as_of: date,
    ) -> dict[str, Any]:
        ctx: dict[str, Any] = {"market": market}

        stock_df = self.frames.get(ticker)
        if stock_df is None or stock_df.empty:
            # No price data at all - return market-only ctx; rules that
            # don't require price data will still evaluate, the rest skip.
            return ctx

        upto = stock_df.sort_index().loc[: pd.Timestamp(as_of)]
        if upto.empty:
            return ctx

        # Technicals — directly from existing helper, on the trailing window
        ctx.update(compute_indicators(upto))

        # Index reference data
        index_sym = INDEX_SYMBOL[market]
        index_df = self.frames.get(index_sym)
        if index_df is not None and not index_df.empty:
            index_closes = index_df.sort_index().loc[: pd.Timestamp(as_of), "Close"]
            stock_closes = upto["Close"]

            stock_3m = _three_month_return_pct(stock_closes, as_of)
            market_3m = _three_month_return_pct(index_closes, as_of)
            if stock_3m is not None:
                ctx["stock_return_3m_pct"] = stock_3m
            if market_3m is not None:
                ctx["market_return_3m_pct"] = market_3m
                # If we don't have a real sector ETF, fall back to market
                # so MACRO-004 has *something* to evaluate.
                ctx.setdefault("sector_return_3m_pct", market_3m)

            beta = _beta(stock_closes, index_closes, as_of)
            if beta is not None:
                ctx["beta"] = beta

            regime = _market_regime(index_closes, as_of)
            if regime is not None:
                ctx["market_regime"] = regime

        # VIX
        vix_df = self.frames.get(VIX_SYMBOL[market])
        if vix_df is not None and not vix_df.empty:
            ctx.update(_vix_block(vix_df["Close"], as_of))

        # Macro defaults: no FRED connection, but the rule_evaluator's
        # graceful-skip handles missing keys. We DO set a few low-risk
        # defaults so MACRO rules that need lists at least see them.
        ctx.setdefault("favorable_sectors_for_cuts", [])
        ctx.setdefault("unfavorable_sectors_for_hikes", [])

        return ctx


# ---------------------------------------------------------------------------
# yfinance fetcher (live)
# ---------------------------------------------------------------------------


def fetch_history(
    ticker: str,
    market: Market,
    start: date,
    end: date,
    *,
    extra_symbols: list[str] | None = None,
) -> HistoricalFrames:
    """Pull all OHLC frames the backtest needs, in one yfinance batch.

    Includes the stock, the market index, and the VIX. Anything that
    fails returns an empty frame (we never let one missing series kill
    the whole backtest).
    """
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover - declared in pyproject
        raise RuntimeError("yfinance is required for backtests") from e

    symbols = [ticker, INDEX_SYMBOL[market], VIX_SYMBOL[market]] + (extra_symbols or [])
    frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        try:
            df = yf.download(
                sym,
                start=start.isoformat(),
                end=(end.toordinal() + 1 and end.isoformat()),
                progress=False,
                auto_adjust=True,
                actions=False,
                threads=False,
            )
            if df is None or df.empty:
                logger.warning("yfinance returned no data for %s", sym)
                frames[sym] = pd.DataFrame()
                continue
            # yfinance multi-ticker downloads return MultiIndex columns;
            # single-ticker is flat. Normalise to flat.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            # Ensure we have the standard column names and a date index
            df.index = pd.to_datetime(df.index).normalize()
            frames[sym] = df
        except Exception as e:  # pragma: no cover - network errors
            logger.warning("yfinance fetch failed for %s: %s", sym, e)
            frames[sym] = pd.DataFrame()
    return HistoricalFrames(frames=frames)


__all__ = [
    "HistoricalContextBuilder",
    "HistoricalFrames",
    "INDEX_SYMBOL",
    "NoopBuilder",
    "VIX_SYMBOL",
    "fetch_history",
]

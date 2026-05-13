"""Assembles the RuleEvaluator context from five providers in parallel.

Routing
-------
- Upstox:    quotes, OHLC candles (→ technicals).
- Screener:  Indian fundamentals (ROE, FCF yield, EPS growth, …).
- NSE:       India VIX, FII/DII flows, option-chain PCR, NIFTY trend.
- Yahoo:     US fundamentals/OHLC, sector/market index history (kept for
             cross-market support and as a fallback when an Indian source
             returns nothing).
- GDELT:     14-day news sentiment + negative-volume spike (works for IN/US).

All five blocks run concurrently via ``asyncio.gather`` with a 12s global
budget. On partial failure (one provider times out) the failure is logged
and the remaining context is returned with the missing fields simply
absent — the rule engine treats absent fields as "skip this rule".

CLI
---
    python -m packages.data.context_builder AAPL US
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from packages.data.providers.base import MarketDataProvider
from packages.data.providers.technicals import compute_indicators
from packages.shared.config import (
    UPSTOX_TO_PROVIDER_INTERVAL,
    ModeConfig,
    lookback_days_for_chart,
)
from packages.shared.schemas import ChartConfig, Fundamentals, Market

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Static lookup tables
# ---------------------------------------------------------------------------

SECTOR_CLASSIFICATION: dict[str, str] = {
    "technology": "cyclical",
    "consumer_cyclical": "cyclical",
    "financials": "cyclical",
    "industrials": "cyclical",
    "materials": "cyclical",
    "energy": "cyclical",
    "real_estate": "cyclical",
    "consumer_defensive": "defensive",
    "utilities": "defensive",
    "healthcare": "defensive",
}

FAVORABLE_SECTORS_FOR_CUTS = [
    "technology", "growth", "real_estate", "utilities", "consumer_cyclical"
]
UNFAVORABLE_SECTORS_FOR_HIKES = [
    "technology", "growth", "real_estate", "utilities", "consumer_cyclical"
]

SECTOR_ETF_US: dict[str, str] = {
    "technology": "XLK",
    "financials": "XLF",
    "healthcare": "XLV",
    "energy": "XLE",
    "consumer_cyclical": "XLY",
    "consumer_defensive": "XLP",
    "industrials": "XLI",
    "materials": "XLB",
    "utilities": "XLU",
    "real_estate": "XLRE",
    "communication_services": "XLC",
}
SECTOR_INDEX_IN: dict[str, str] = {
    "technology": "^CNXIT",
    "financials": "^NSEBANK",
    "energy": "^CNXENERGY",
    "consumer_cyclical": "^CNXAUTO",
    "consumer_defensive": "^CNXFMCG",
    "healthcare": "^CNXPHARMA",
}

MARKET_INDEX = {"IN": "^NSEI"}
VIX_SYMBOL = {"IN": "^INDIAVIX"}
ALLOWED_MARKETS: tuple[Market, ...] = ("IN",)
UPSTOX_EXCHANGE = "NSE"

GLOBAL_BUILD_TIMEOUT_S = 30.0


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class ContextBuilder:
    def __init__(
        self,
        providers: list[MarketDataProvider],
        screener: Any | None = None,
        nse: Any | None = None,
        gdelt: Any | None = None,
        mode_config: ModeConfig | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ContextBuilder requires at least one MarketDataProvider")
        self.providers = providers
        self.screener = screener
        self.nse = nse
        self.gdelt = gdelt
        # When ``mode_config.skip_screener`` is True, ``_fundamentals_block``
        # bypasses the (slow) Screener HTML scrape. We deliberately keep
        # the Yahoo fallback in place — its fundamentals call is cheap
        # and still useful for sector/beta lookup. ``None`` means "no
        # mode-aware tuning"; the builder behaves exactly as before.
        self.mode_config = mode_config

    def _providers_for(self, market: Market) -> list[MarketDataProvider]:
        return [p for p in self.providers if market in p.supported_markets]

    @property
    def _yahoo(self) -> Any | None:
        for p in self.providers:
            if getattr(p, "name", None) == "yahoo":
                return p
        return None

    @property
    def _upstox(self) -> Any | None:
        for p in self.providers:
            if getattr(p, "name", None) == "upstox":
                return p
        return None

    async def _try_each(
        self, market: Market, op: str, *args: Any, **kwargs: Any
    ) -> Any:
        last_exc: Exception | None = None
        for p in self._providers_for(market):
            try:
                return await getattr(p, op)(*args, **kwargs)
            except NotImplementedError:
                continue
            except Exception as e:
                logger.warning("%s.%s failed: %s", p.name, op, e)
                last_exc = e
        if last_exc:
            raise last_exc
        raise LookupError(f"No provider implements {op} for market={market}")

    # ------------------------------------------------------------------ build
    async def build(self, ticker: str, market: Market) -> dict[str, Any]:
        if market not in ALLOWED_MARKETS:
            raise ValueError(
                f"Only Indian market (IN) is supported in this deployment; got market={market}"
            )
        if not self._providers_for(market):
            raise LookupError(f"No provider registered for market={market}")

        ctx: dict[str, Any] = {"market": market}

        # Five top-level blocks run in parallel under a single 12s budget.
        # Any block that misses the deadline is logged and dropped.
        blocks = [
            self._safe_block("fundamentals", self._fundamentals_block(ticker, market)),
            self._safe_block("technicals", self._technicals_block(ticker, market)),
            self._safe_block("nse", self._nse_block(ticker, market)),
            self._safe_block("vix", self._vix_block(market)),
            self._safe_block("gdelt", self._gdelt_block(ticker, market)),
        ]
        try:
            gathered = await asyncio.wait_for(
                asyncio.gather(*blocks),
                timeout=GLOBAL_BUILD_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "context build hit %.1fs global timeout — returning partial context",
                GLOBAL_BUILD_TIMEOUT_S,
            )
            gathered = []

        for _name, block in gathered:
            if block:
                ctx.update(block)

        # Guaranteed safety nets for risk pillar inputs. RISK-001 (beta) and
        # RISK-003 (vix_level + vix_change_5d_pct + fundamental_score) skip
        # entirely if any required field is missing — that drops the whole
        # risk pillar to neutral 50.0. We backfill defensible defaults so
        # the rules always evaluate.
        ctx.setdefault("vix_level", 18.0)        # long-run India VIX mean
        ctx.setdefault("vix_change_5d_pct", 0.0) # neutral 5d delta
        ctx.setdefault("beta", 1.0)              # market-neutral beta

        # Relative-strength depends on the sector resolved from fundamentals,
        # so it runs in a 2nd pass once the parallel batch has finished.
        sector = ctx.get("sector") or ctx.get("stock_sector")
        rs_block = await self._safe_block(
            "relative_strength",
            self._relative_strength_block(ticker, market, sector),
        )
        if rs_block[1]:
            ctx.update(rs_block[1])

        if sector and "stock_sector_classification" not in ctx:
            ctx["stock_sector_classification"] = SECTOR_CLASSIFICATION.get(sector, "cyclical")
        ctx.setdefault("favorable_sectors_for_cuts", FAVORABLE_SECTORS_FOR_CUTS)
        ctx.setdefault("unfavorable_sectors_for_hikes", UNFAVORABLE_SECTORS_FOR_HIKES)

        ctx["market_regime"] = self._market_regime(ctx)

        try:
            ctx["fundamental_score"] = await asyncio.to_thread(
                self._compute_fundamental_score, ticker, market, ctx
            )
        except Exception as e:
            logger.warning("fundamental_score computation failed: %s", e)

        return ctx

    @staticmethod
    async def _safe_block(name: str, coro: Any) -> tuple[str, dict[str, Any]]:
        try:
            result = await coro
            return name, result or {}
        except Exception as e:
            logger.warning("block '%s' failed: %s", name, e)
            return name, {}

    # -------------------------------------------------------- fundamentals
    async def _fundamentals_block(self, ticker: str, market: Market) -> dict[str, Any]:
        # IN: Screener is the canonical fundamentals source. US: provider chain
        # (typically Yahoo). On Screener failure for IN we still fall back to
        # the provider chain so we never end up with an empty fundamentals block
        # when a yfinance read would have worked.
        skip_screener = bool(self.mode_config and self.mode_config.skip_screener)
        screener_data: dict[str, Any] = {}
        if skip_screener:
            # Mode-aware short-circuit: intraday / short-term runs give
            # fundamentals 0 weight in the composite, so we don't pay the
            # Screener scrape latency for data we won't score. We still
            # fall through to the provider chain (Yahoo) below — its
            # fundamentals call is cheap and supplies sector / beta that
            # other blocks (relative-strength, sector-rotation rules)
            # need regardless of mode.
            logger.info(
                "skipping Screener fundamentals fetch (mode=%s)",
                self.mode_config.mode if self.mode_config else None,
            )
        elif market == "IN" and self.screener is not None:
            try:
                scraped = await self.screener.get_fundamentals(ticker)
            except Exception as e:
                logger.warning("screener fundamentals failed: %s", e)
                scraped = {}
            if scraped:
                # Strip None entries so downstream "key in ctx" checks behave.
                screener_data = {k: v for k, v in scraped.items() if v is not None}

        # Always fetch Yahoo fundamentals too — Screener doesn't expose
        # ``beta`` (needed by RISK-001) or ``target_price_avg`` (used by
        # decision agent for target_price). Screener data wins on conflict
        # since it's the canonical IN source.
        yahoo_extras: dict[str, Any] = {}
        try:
            fund: Fundamentals | None = await self._try_each(
                market, "get_fundamentals", ticker, market
            )
        except (LookupError, NotImplementedError):
            fund = None
        except Exception as e:
            logger.warning("yahoo fundamentals failed for %s: %s", ticker, e)
            fund = None

        if fund is not None:
            for key in (
                "eps_yoy_pct",
                "eps_qoq_pct",
                "eps_misses_consecutive",
                "revenue_yoy_pct",
                "revenue_decline_quarters_consecutive",
                "net_margin_current",
                "net_margin_2q_ago",
                "roe_pct",
                "roa_pct",
                "fcf_yield_pct",
                "fcf_negative_quarters_consecutive",
                "debt_to_equity",
                "current_ratio",
                "quick_ratio",
                "interest_coverage_ratio",
                "pe_ratio",
                "forward_pe",
                "peg_ratio",
                "ev_ebitda",
                "pb_ratio",
                "dividend_yield_pct",
                "payout_ratio_pct",
            ):
                v = getattr(fund, key, None)
                if v is not None:
                    yahoo_extras[key] = v

            if fund.sector:
                yahoo_extras["sector"] = fund.sector
                yahoo_extras["stock_sector"] = fund.sector

            for key in (
                "is_growth_stock",
                "is_financial_sector",
                "revenue_growing",
                "margin_improving",
                "earnings_declining",
                "company_age_years",
                "dividend_growth_5y_pct",
                "beta",
                "target_price_avg",
                "foreign_revenue_pct",
            ):
                v = fund.extra.get(key)
                if v is not None:
                    yahoo_extras[key] = v

        # Merge: start from Yahoo, overlay Screener (Screener wins on conflict
        # for IN since it's the canonical fundamentals source). Yahoo-only
        # fields like ``beta`` and ``target_price_avg`` survive the merge.
        out: dict[str, Any] = {**yahoo_extras, **screener_data}

        # Sane default for beta when both sources missed it. RISK-001 reads
        # this; without a value the rule skips and the risk pillar lands at
        # neutral 50.0. 1.0 is the market-cap-weighted default for an Indian
        # large-cap and produces a "neutral" tier in RISK-001 either way.
        out.setdefault("beta", 1.0)

        out.setdefault("debt_to_equity_yoy_change", 0.0)
        out.setdefault("debt_to_equity_change_yoy", 0.0)

        return out

    # ---------------------------------------------------------- technicals
    async def _technicals_block(self, ticker: str, market: Market) -> dict[str, Any]:
        """Fetch daily candles and derive TA indicators.

        We always fetch DAILY candles regardless of the run mode's
        ``ChartConfig.primary_interval``. Reasons:

          1. ``compute_indicators`` derives every TA field (MA-50/200,
             RSI-14 (+ RSI-3; intraday aliases rsi_14 from rsi_3), MACD-12-26-9,
             Bollinger-20, 52-week range,
             support/resistance) from daily bars. The chart config is
             a *display* hint for the frontend, not a TA window.
          2. Upstox v2 historical-candle API only accepts
             (1minute, 30minute, day, week, month) — daily is the most
             reliable interval for non-Nifty50 names.
          3. Several rules (TREND-001 golden-cross, TREND-002 52-week
             extremes) need ≥200 daily bars regardless of mode.
        """
        end = date.today()
        start = end - timedelta(days=400)
        try:
            bars = await self._try_each(
                market, "get_ohlc", ticker, market, "1d", start, end
            )
        except Exception as e:
            logger.warning("technicals: get_ohlc failed for %s: %s", ticker, e)
            bars = []

        if not bars or len(bars) < 30:
            logger.warning(
                "technicals: %s returned only %d bars (need ≥30); pillar will skip",
                ticker, len(bars) if bars else 0,
            )
            return {}

        mode = self.mode_config.mode if self.mode_config is not None else None
        out = await asyncio.to_thread(_indicators_from_bars, bars, mode)
        chart = self._effective_chart_config()
        out.setdefault("primary_interval", chart.primary_interval)
        out.setdefault("ta_compute_interval", "1d")
        logger.info("technicals: computed %d indicator fields for %s", len(out), ticker)
        return out

    def _effective_chart_config(self) -> ChartConfig:
        """Return the ChartConfig the technicals block should fetch on.

        Falls back to a daily / 400-bar default when no mode is set so
        callers that construct ``ContextBuilder`` without a ``ModeConfig``
        (legacy code, eval/backtest harnesses) keep their pre-mode
        behaviour exactly.
        """
        if self.mode_config is not None and self.mode_config.chart_config is not None:
            return self.mode_config.chart_config
        return ChartConfig(
            primary_interval="1day",
            secondary_interval=None,
            context_interval=None,
            polling_interval_seconds=86400,
            lookback_candles=400,
        )

    # -------------------------------------------------- relative strength
    async def _relative_strength_block(
        self, ticker: str, market: Market, sector: str | None
    ) -> dict[str, Any]:
        yahoo = self._yahoo
        if yahoo is None:
            return {}
        end = date.today()
        start = end - timedelta(days=120)
        market_sym = MARKET_INDEX[market]

        sector_sym: str | None = None
        if sector:
            sector_sym = (SECTOR_ETF_US if market == "US" else SECTOR_INDEX_IN).get(sector)

        async def _stock_returns() -> list[Any]:
            return await self._try_each(market, "get_ohlc", ticker, market, "1d", start, end)

        async def _idx(symbol: str) -> list[Any]:
            return await yahoo.get_index_history(symbol, days=120)

        gathered: list[Any] = await asyncio.gather(
            _stock_returns(),
            _idx(market_sym),
            _idx(sector_sym) if sector_sym else _empty(),
            return_exceptions=True,
        )
        stock_bars, market_bars, sector_bars = (
            r if not isinstance(r, BaseException) else [] for r in gathered
        )

        out: dict[str, Any] = {}
        stock_3m = _three_month_return(stock_bars)
        market_3m = _three_month_return(market_bars)
        sector_3m = _three_month_return(sector_bars)
        if stock_3m is not None:
            out["stock_return_3m_pct"] = stock_3m
        if market_3m is not None:
            out["market_return_3m_pct"] = market_3m
        if sector_3m is not None:
            out["sector_return_3m_pct"] = sector_3m
        elif market_3m is not None:
            out["sector_return_3m_pct"] = market_3m
        if stock_bars and market_bars:
            out["rs_line_at_3m_high"] = _rs_at_high(stock_bars, market_bars)
        return out

    # ---------------------------------------------------------------- VIX
    async def _vix_block(self, market: Market) -> dict[str, Any]:
        """Fetch India VIX. Tries NSE allIndices first, then Yahoo ^INDIAVIX,
        finally falls back to a conservative neutral default so RISK-003
        never skips on a weekend / NSE-blocked-IP run."""
        # IN: prefer the live NSE allIndices snapshot.
        if market == "IN" and self.nse is not None:
            try:
                vix_block = await self.nse.get_india_vix()
            except Exception as e:
                logger.warning("nse vix failed: %s", e)
                vix_block = {}
            if vix_block.get("vix_level") is not None:
                logger.info("vix: NSE returned level=%.2f", vix_block["vix_level"])
                return vix_block

        # Yahoo fallback for ^INDIAVIX
        yahoo = self._yahoo
        if yahoo is not None:
            try:
                bars = await yahoo.get_index_history(VIX_SYMBOL[market], days=10)
            except Exception as e:
                logger.warning("yahoo vix fallback failed: %s", e)
                bars = []
            if bars:
                latest = float(bars[-1].close)
                out: dict[str, Any] = {"vix_level": latest}
                if len(bars) >= 6:
                    five_back = float(bars[-6].close)
                    if five_back:
                        out["vix_change_5d_pct"] = (latest - five_back) / five_back * 100.0
                logger.info("vix: Yahoo returned level=%.2f", latest)
                return out

        # Last-resort default: neutral VIX. Better than letting RISK-003 skip
        # entirely (which drops the whole risk pillar to 50.0). 18.0 is the
        # long-run India VIX mean and produces a "neutral" tier in RISK-003.
        logger.warning("vix: both NSE and Yahoo failed; using neutral default 18.0")
        return {"vix_level": 18.0, "vix_change_5d_pct": 0.0}

    # --------------------------------------------------------------- NSE
    async def _nse_block(self, ticker: str, market: Market) -> dict[str, Any]:
        """FII/DII flows, option-chain PCR, NIFTY trend (IN only)."""
        if market != "IN" or self.nse is None:
            return {}

        flows_t = asyncio.create_task(self.nse.get_fii_dii_flows())
        pcr_t = asyncio.create_task(self.nse.get_option_chain_pcr(ticker))
        sma_t = asyncio.create_task(self._nifty_sma_50())

        flows, pcr, sma_50 = await asyncio.gather(
            flows_t, pcr_t, sma_t, return_exceptions=True
        )

        out: dict[str, Any] = {}
        if isinstance(flows, dict):
            out.update({k: v for k, v in flows.items() if v is not None})
        if isinstance(pcr, dict):
            out.update({k: v for k, v in pcr.items() if v is not None})

        sma_value = sma_50 if isinstance(sma_50, (int, float)) else None
        try:
            trend = await self.nse.get_nifty_trend(sma_50=sma_value)
        except Exception as e:
            logger.warning("nse nifty trend failed: %s", e)
            trend = {}
        if isinstance(trend, dict):
            out.update({k: v for k, v in trend.items() if v is not None})
        return out

    async def _nifty_sma_50(self) -> float | None:
        """Compute a 50-day SMA of NIFTY 50 close from Upstox candles.

        Returns None if Upstox is not configured or the fetch fails — callers
        downgrade gracefully to "no trend" when this is missing.
        """
        upstox = self._upstox
        if upstox is None:
            return None
        try:
            end = date.today()
            start = end - timedelta(days=80)
            # NIFTY 50 instrument key on Upstox is NSE_INDEX|Nifty 50
            # — we register it via the symbol→key resolver on the fly.
            from packages.data.providers.upstox import _DEFAULT_ISINS  # noqa: F401

            bars = await upstox.get_ohlc("NIFTY", "IN", "1d", start, end)
        except Exception as e:
            logger.debug("nifty 50-sma fetch failed: %s", e)
            return None
        if not bars or len(bars) < 50:
            return None
        last_50 = bars[-50:]
        return sum(float(b.close) for b in last_50) / 50.0

    # -------------------------------------------------------------- GDELT
    async def _gdelt_block(self, ticker: str, market: Market) -> dict[str, Any]:
        if self.gdelt is None:
            return {}
        return await self.gdelt.get_sentiment_block(ticker, market)

    # ----------------------------------------------- derived: market_regime
    @staticmethod
    def _market_regime(ctx: dict[str, Any]) -> str:
        """Without FRED we can only use the signals we still have on hand:
        NIFTY trend (IN) plus VIX level. Both bullish → bull, both bearish
        → bear, otherwise neutral."""
        nifty_trend = ctx.get("nifty_trend")
        vix = ctx.get("vix_level")
        bullish = nifty_trend == "uptrend" and (vix is None or vix < 20)
        bearish = nifty_trend == "downtrend" or (vix is not None and vix > 25)
        if bullish:
            return "bull"
        if bearish:
            return "bear"
        return "neutral"

    # --------------------------------- derived: fundamental_score (2nd pass)
    @staticmethod
    def _compute_fundamental_score(ticker: str, market: Market, ctx: dict[str, Any]) -> float:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
        from rule_evaluator import RuleEvaluator  # type: ignore[import-not-found]

        rules_path = Path(__file__).resolve().parents[1] / "core" / "rules.json"
        ev = RuleEvaluator(rules_path)
        result = ev.evaluate(ticker, market, ctx)
        fund = result.pillar_scores.get("fundamentals", 50.0)
        bs = result.pillar_scores.get("balance_sheet", 50.0)
        return (fund + bs) / 2.0


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

async def _empty() -> list[Any]:
    return []


def _three_month_return(bars: list[Any]) -> float | None:
    if not bars or len(bars) < 2:
        return None
    cutoff = bars[-1].timestamp - timedelta(days=90)
    earliest = next(
        (b for b in bars if b.timestamp >= cutoff),
        bars[0],
    )
    start_close = float(earliest.close)
    end_close = float(bars[-1].close)
    if not start_close:
        return None
    return (end_close - start_close) / start_close * 100.0


def _rs_at_high(stock_bars: list[Any], market_bars: list[Any]) -> bool:
    import pandas as pd

    s = pd.Series(
        [float(b.close) for b in stock_bars],
        index=pd.to_datetime([b.timestamp for b in stock_bars]),
    )
    m = pd.Series(
        [float(b.close) for b in market_bars],
        index=pd.to_datetime([b.timestamp for b in market_bars]),
    )
    aligned = s.to_frame("s").join(m.to_frame("m"), how="inner").dropna()
    if aligned.empty:
        return False
    rs = aligned["s"] / aligned["m"]
    if rs.empty:
        return False
    return bool(rs.iloc[-1] >= rs.max() * 0.999)


def _indicators_from_bars(
    bars: list[Any],
    mode: str | None = None,
) -> dict[str, Any]:
    import pandas as pd

    df = pd.DataFrame(
        {
            "Open": [float(b.open) for b in bars],
            "High": [float(b.high) for b in bars],
            "Low": [float(b.low) for b in bars],
            "Close": [float(b.close) for b in bars],
            "Volume": [b.volume for b in bars],
        },
        index=pd.to_datetime([b.timestamp for b in bars]),
    )
    out = compute_indicators(df)
    # Intraday: rules still reference rsi_14 — feed them the fast RSI(3) value.
    if mode == "intraday" and "rsi_3" in out:
        out["rsi_14"] = out["rsi_3"]
    return out


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _build_default_providers(market: Market) -> tuple[list[MarketDataProvider], Any, Any, Any]:
    from packages.data.providers.yahoo import YahooFinanceProvider

    providers: list[MarketDataProvider] = []
    if market == "IN":
        try:
            from packages.data.providers.upstox import UpstoxProvider

            providers.append(UpstoxProvider())
        except (ImportError, RuntimeError) as e:
            logger.info("Upstox unavailable (%s) — Yahoo only for IN", e)
    providers.append(YahooFinanceProvider())

    screener = nse = gdelt = None
    if market == "IN":
        try:
            from packages.data.providers.screener import ScreenerProvider

            screener = ScreenerProvider()
        except (ImportError, RuntimeError) as e:
            logger.info("Screener unavailable: %s", e)
        try:
            from packages.data.providers.nse import NSEProvider

            nse = NSEProvider()
        except (ImportError, RuntimeError) as e:
            logger.info("NSE unavailable: %s", e)
    try:
        from packages.data.providers.gdelt import GDELTProvider

        gdelt = GDELTProvider()
    except ImportError as e:
        logger.info("GDELT unavailable: %s", e)

    return providers, screener, nse, gdelt


async def _smoke_test(ticker: str, market: Market) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
    from rule_evaluator import RuleEvaluator  # type: ignore[import-not-found]

    providers, screener, nse, gdelt = _build_default_providers(market)
    builder = ContextBuilder(providers, screener=screener, nse=nse, gdelt=gdelt)
    print(f"Building context for {ticker} ({market})…")
    import time

    t0 = time.monotonic()
    ctx = await builder.build(ticker, market)
    elapsed = time.monotonic() - t0
    print(f"\n--- Context (built in {elapsed:.2f}s) ---")
    print(json.dumps(ctx, default=str, indent=2, sort_keys=True))

    rules_path = Path(__file__).resolve().parents[1] / "core" / "rules.json"
    evaluator = RuleEvaluator(rules_path)
    result = evaluator.evaluate(ticker, market, ctx)
    print("\n--- Evaluation ---")
    print(result.summary())
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("ticker")
    parser.add_argument("market", choices=["IN", "US"])
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_smoke_test(args.ticker, args.market))


if __name__ == "__main__":
    raise SystemExit(main())

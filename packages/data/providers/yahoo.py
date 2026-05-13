"""Yahoo Finance adapter (yfinance, sync → wrapped in asyncio.to_thread).

Caches via Redis: quotes 5s, fundamentals 1h, news 15m. Rate-limited to 60
req/min by default.

yfinance keys are mapped explicitly to our `Fundamentals` schema; do not pass
through unknown fields (yfinance's surface is unstable).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from packages.data.providers.base import MarketDataProvider, OHLCInterval
from packages.data.providers.cache import RedisCache
from packages.data.providers.rate_limit import RateLimiter
from packages.shared.schemas import (
    CorporateAction,
    Fundamentals,
    Market,
    NewsItem,
    OHLCBar,
    Quote,
)

logger = logging.getLogger(__name__)


_QUOTE_TTL = 5
_NEWS_TTL = 15 * 60
_FUNDAMENTALS_TTL = 60 * 60
_OHLC_TTL = 5 * 60

# NSE headline indices: bare symbols → yfinance tickers (^… avoids the .NS suffix).
_IN_INDEX_YFIN: dict[str, str] = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "^CNXFIN",
    "MIDCPNIFTY": "^NSEMDCP50",
}


class YahooFinanceProvider(MarketDataProvider):
    name = "yahoo"
    supported_markets: tuple[Market, ...] = ("IN", "US")

    def __init__(
        self,
        cache: RedisCache | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.cache = cache if cache is not None else RedisCache()
        self.rate_limiter = rate_limiter or RateLimiter.per_minute(60)

    @staticmethod
    def _normalize_ticker(ticker: str, market: Market) -> str:
        """Indian stocks need an exchange suffix on yfinance.

        If the caller passes `"RELIANCE"` we route it to `"RELIANCE.NS"`.
        Headline indices (``NIFTY``, ``BANKNIFTY``, …) map to ``^NSEI``-style
        symbols. Already-suffixed tickers (``.NS``, ``.BO``) pass through.
        """
        if market != "IN":
            return ticker
        if ticker.startswith("^"):
            return ticker
        bare = ticker.upper().removesuffix(".NS").removesuffix(".BO")
        if bare in _IN_INDEX_YFIN:
            return _IN_INDEX_YFIN[bare]
        if ticker.endswith((".NS", ".BO")):
            return ticker
        return f"{ticker}.NS"

    # ------------------------------------------------------------------ quote
    async def get_quote(self, ticker: str, market: Market) -> Quote:
        cache_key = f"yahoo:quote:{market}:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Quote.model_validate_json(cached)

        await self.rate_limiter.acquire()
        symbol = self._normalize_ticker(ticker, market)
        info = await asyncio.to_thread(self._fast_info_sync, symbol)

        quote = Quote(
            ticker=ticker,
            market=market,
            price=Decimal(str(info["price"])),
            currency=info["currency"],
            timestamp=datetime.now(UTC),
            change_pct=info.get("change_pct"),
            volume=info.get("volume"),
        )
        await self.cache.set(cache_key, quote.model_dump_json(), _QUOTE_TTL)
        return quote

    @staticmethod
    def _fast_info_sync(symbol: str) -> dict[str, Any]:
        import yfinance as yf

        t = yf.Ticker(symbol)
        fast = t.fast_info
        last = float(fast["lastPrice"])
        prev = float(fast.get("previousClose") or last)
        return {
            "price": last,
            "currency": fast.get("currency") or "USD",
            "volume": int(fast.get("lastVolume") or 0) or None,
            "change_pct": (last - prev) / prev * 100 if prev else None,
        }

    # ------------------------------------------------------------------ ohlc
    async def get_ohlc(
        self,
        ticker: str,
        market: Market,
        interval: OHLCInterval,
        start: date,
        end: date,
    ) -> list[OHLCBar]:
        cache_key = f"yahoo:ohlc:{market}:{ticker}:{interval}:{start}:{end}"
        cached = await self.cache.get(cache_key)
        if cached:
            import json

            payload = json.loads(cached)
            return [OHLCBar.model_validate(b) for b in payload]

        await self.rate_limiter.acquire()
        symbol = self._normalize_ticker(ticker, market)
        rows = await asyncio.to_thread(self._history_sync, symbol, interval, start, end)
        bars = [
            OHLCBar(
                ticker=ticker,
                timestamp=ts,
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(l)),
                close=Decimal(str(c)),
                volume=int(v),
                interval=cast(Any, interval),
            )
            for ts, o, h, l, c, v in rows
        ]
        import json

        await self.cache.set(
            cache_key,
            json.dumps([b.model_dump(mode="json") for b in bars], default=str),
            _OHLC_TTL,
        )
        return bars

    @staticmethod
    def _history_sync(
        symbol: str, interval: str, start: date, end: date
    ) -> list[tuple[datetime, float, float, float, float, float]]:
        import yfinance as yf

        df = yf.Ticker(symbol).history(start=start, end=end, interval=interval, auto_adjust=False)
        out: list[tuple[datetime, float, float, float, float, float]] = []
        for ts, row in df.iterrows():
            ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            out.append(
                (
                    ts_dt,
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row["Volume"]),
                )
            )
        return out

    # ----------------------------------------------------------- fundamentals
    async def get_fundamentals(self, ticker: str, market: Market) -> Fundamentals:
        cache_key = f"yahoo:fund:{market}:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Fundamentals.model_validate_json(cached)

        await self.rate_limiter.acquire()
        symbol = self._normalize_ticker(ticker, market)
        raw = await asyncio.to_thread(self._fundamentals_sync, symbol)
        fund = self._map_fundamentals(ticker, market, raw)
        await self.cache.set(cache_key, fund.model_dump_json(), _FUNDAMENTALS_TTL)
        return fund

    @staticmethod
    def _fundamentals_sync(symbol: str) -> dict[str, Any]:
        import yfinance as yf

        t = yf.Ticker(symbol)
        info = dict(t.info or {})
        # Quarterly statements drive QoQ / consecutive-decline metrics.
        try:
            qis = t.quarterly_income_stmt
        except Exception:
            qis = None
        try:
            qcf = t.quarterly_cashflow
        except Exception:
            qcf = None
        try:
            divs = t.dividends
        except Exception:
            divs = None
        return {"info": info, "qis": qis, "qcf": qcf, "divs": divs}

    @staticmethod
    def _pct(x: Any) -> float | None:
        """yfinance reports many ratios as fractions (0.28 → 28%). Guard None/NaN."""
        if x is None:
            return None
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        if v != v:  # NaN check
            return None
        return v * 100.0

    @staticmethod
    def _num(x: Any) -> float | None:
        if x is None:
            return None
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        return None if v != v else v

    @classmethod
    def _map_fundamentals(
        cls, ticker: str, market: Market, raw: dict[str, Any]
    ) -> Fundamentals:
        info = raw["info"]
        qis = raw["qis"]
        qcf = raw["qcf"]
        divs = raw["divs"]

        sector = info.get("sector")
        sector_norm = cls._normalize_sector(sector)
        is_financial = sector_norm in {"financials", "financial_services"}

        # FCF yield = freeCashflow / marketCap
        fcf = info.get("freeCashflow")
        mcap = info.get("marketCap")
        fcf_yield = (
            float(fcf) / float(mcap) * 100.0
            if fcf and mcap and float(mcap) != 0
            else None
        )

        # Quarterly-derived metrics
        eps_qoq = cls._eps_qoq_pct(qis)
        eps_misses = None  # yfinance has no estimate vs actual history; left absent
        rev_decline = cls._consec_decline_quarters(qis, "Total Revenue")
        fcf_neg_q = cls._consec_negative_quarters(qcf, "Free Cash Flow")
        nm_2q = cls._net_margin_2q_ago(qis)
        revenue_growing = cls._revenue_growing(qis)
        margin_improving = cls._margin_improving(qis)

        # Company age from first trade date. yfinance has flip-flopped between
        # firstTradeDateEpochUtc (seconds) and firstTradeDateMilliseconds.
        company_age_years: float | None = None
        for key, divisor in (
            ("firstTradeDateEpochUtc", 1),
            ("firstTradeDateMilliseconds", 1000),
        ):
            v = info.get(key)
            if v:
                try:
                    first_dt = datetime.fromtimestamp(int(v) / divisor, tz=UTC)
                    company_age_years = (datetime.now(UTC) - first_dt).days / 365.25
                    break
                except (TypeError, ValueError, OSError):
                    continue

        # Dividend 5y growth from dividend series
        div_growth_5y = cls._dividend_growth_5y_pct(divs)

        # Earnings declining flag: trailing EPS lower than 2 quarters back
        earnings_declining = cls._earnings_declining(qis)

        # Interest coverage from EBIT / |Interest Expense| (last 4 quarters)
        interest_coverage = cls._interest_coverage(qis)

        # debtToEquity is reported as a *percent* (e.g. 195 for 1.95), unify to ratio
        de_raw = cls._num(info.get("debtToEquity"))
        debt_to_equity = de_raw / 100.0 if de_raw is not None else None

        extra: dict[str, Any] = {
            "industry": info.get("industry"),
            "is_financial_sector": is_financial,
            "is_growth_stock": cls._is_growth_stock(info),
            "revenue_growing": revenue_growing,
            "margin_improving": margin_improving,
            "earnings_declining": earnings_declining,
            "fcf_negative_quarters_consecutive": fcf_neg_q,
            "revenue_decline_quarters_consecutive": rev_decline,
            "company_age_years": company_age_years,
            "dividend_growth_5y_pct": div_growth_5y,
            "beta": cls._num(info.get("beta")),
            "target_price_avg": cls._num(info.get("targetMeanPrice")),
            "foreign_revenue_pct": cls._foreign_revenue_pct(info),
            # Industry-aggregate benchmarks (sector_pe_avg, industry_avg_margin,
            # industry_ev_ebitda_median, pe_5y_avg) not provided by yfinance —
            # would require a paid peer-fundamentals service.
        }
        if eps_misses is not None:
            extra["eps_misses_consecutive"] = eps_misses

        return Fundamentals(
            ticker=ticker,
            market=market,
            as_of=date.today(),
            eps_yoy_pct=cls._pct(info.get("earningsGrowth")),
            eps_qoq_pct=eps_qoq,
            eps_misses_consecutive=eps_misses,
            revenue_yoy_pct=cls._pct(info.get("revenueGrowth")),
            revenue_decline_quarters_consecutive=rev_decline,
            net_margin_current=cls._pct(info.get("profitMargins")),
            net_margin_2q_ago=nm_2q,
            roe_pct=cls._pct(info.get("returnOnEquity")),
            roa_pct=cls._pct(info.get("returnOnAssets")),
            fcf_yield_pct=fcf_yield,
            fcf_negative_quarters_consecutive=fcf_neg_q,
            debt_to_equity=debt_to_equity,
            current_ratio=cls._num(info.get("currentRatio")),
            quick_ratio=cls._num(info.get("quickRatio")),
            pe_ratio=cls._num(info.get("trailingPE")),
            forward_pe=cls._num(info.get("forwardPE")),
            peg_ratio=cls._num(info.get("pegRatio")),
            interest_coverage_ratio=interest_coverage,
            ev_ebitda=cls._num(info.get("enterpriseToEbitda")),
            pb_ratio=cls._num(info.get("priceToBook")),
            dividend_yield_pct=cls._pct(info.get("dividendYield")),
            payout_ratio_pct=cls._pct(info.get("payoutRatio")),
            sector=sector_norm,
            extra=extra,
        )

    @staticmethod
    def _normalize_sector(sector: Any) -> str | None:
        if not sector:
            return None
        s = str(sector).strip().lower().replace(" ", "_").replace("-", "_")
        # Map yfinance sector names to the keys used in rules.json
        synonyms = {
            "technology": "technology",
            "communication_services": "technology",
            "financial_services": "financials",
            "financials": "financials",
            "real_estate": "real_estate",
            "utilities": "utilities",
            "energy": "energy",
            "basic_materials": "materials",
            "consumer_cyclical": "consumer_cyclical",
            "consumer_defensive": "consumer_defensive",
            "industrials": "industrials",
            "healthcare": "healthcare",
        }
        return synonyms.get(s, s)

    @staticmethod
    def _foreign_revenue_pct(info: dict[str, Any]) -> float | None:
        # yfinance doesn't expose geographic segment revenue; absent unless a
        # future paid feed surfaces it.
        return None

    @staticmethod
    def _is_growth_stock(info: dict[str, Any]) -> bool:
        eg = info.get("earningsGrowth")
        rg = info.get("revenueGrowth")
        try:
            return (eg is not None and float(eg) >= 0.15) or (
                rg is not None and float(rg) >= 0.20
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _eps_qoq_pct(qis: Any) -> float | None:
        if qis is None or getattr(qis, "empty", True):
            return None
        for label in ("Diluted EPS", "Basic EPS"):
            if label in qis.index:
                row = qis.loc[label].dropna()
                if len(row) >= 2:
                    cur, prev = float(row.iloc[0]), float(row.iloc[1])
                    if prev:
                        return (cur - prev) / abs(prev) * 100.0
                    return None
        return None

    @staticmethod
    def _consec_decline_quarters(qis: Any, label: str) -> int | None:
        if qis is None or getattr(qis, "empty", True) or label not in qis.index:
            return None
        series = qis.loc[label].dropna()
        if len(series) < 2:
            return None
        count = 0
        for i in range(len(series) - 1):
            if float(series.iloc[i]) < float(series.iloc[i + 1]):
                count += 1
            else:
                break
        return count

    @staticmethod
    def _consec_negative_quarters(qcf: Any, label: str) -> int | None:
        if qcf is None or getattr(qcf, "empty", True):
            return None
        # Try canonical labels in order
        for key in (label, "Free Cash Flow", "FreeCashFlow"):
            if key in qcf.index:
                series = qcf.loc[key].dropna()
                count = 0
                for v in series:
                    if float(v) < 0:
                        count += 1
                    else:
                        break
                return count
        return None

    @staticmethod
    def _net_margin_2q_ago(qis: Any) -> float | None:
        if qis is None or getattr(qis, "empty", True):
            return None
        if "Net Income" not in qis.index or "Total Revenue" not in qis.index:
            return None
        ni = qis.loc["Net Income"].dropna()
        rev = qis.loc["Total Revenue"].dropna()
        if len(ni) < 3 or len(rev) < 3:
            return None
        try:
            return float(ni.iloc[2]) / float(rev.iloc[2]) * 100.0
        except (ZeroDivisionError, ValueError):
            return None

    @staticmethod
    def _revenue_growing(qis: Any) -> bool | None:
        if qis is None or getattr(qis, "empty", True) or "Total Revenue" not in qis.index:
            return None
        rev = qis.loc["Total Revenue"].dropna()
        if len(rev) < 2:
            return None
        return float(rev.iloc[0]) > float(rev.iloc[1])

    @staticmethod
    def _margin_improving(qis: Any) -> bool | None:
        if qis is None or getattr(qis, "empty", True):
            return None
        if "Net Income" not in qis.index or "Total Revenue" not in qis.index:
            return None
        ni = qis.loc["Net Income"].dropna()
        rev = qis.loc["Total Revenue"].dropna()
        if len(ni) < 2 or len(rev) < 2:
            return None
        try:
            cur = float(ni.iloc[0]) / float(rev.iloc[0])
            prev = float(ni.iloc[1]) / float(rev.iloc[1])
            return cur > prev
        except (ZeroDivisionError, ValueError):
            return None

    @staticmethod
    def _interest_coverage(qis: Any) -> float | None:
        if qis is None or getattr(qis, "empty", True):
            return None
        # Try the canonical labels first; fall back to substring search.
        ebit_row = None
        for label in ("EBIT", "Operating Income", "Total Operating Income As Reported"):
            if label in qis.index:
                ebit_row = qis.loc[label]
                break
        int_row = None
        for label in ("Interest Expense", "Interest Expense Non Operating"):
            if label in qis.index:
                int_row = qis.loc[label]
                break
        if ebit_row is None or int_row is None:
            return None
        ebit_4q = float(ebit_row.dropna().head(4).sum())
        int_4q = float(int_row.dropna().head(4).sum())
        if int_4q == 0:
            return None
        return abs(ebit_4q / int_4q)

    @staticmethod
    def _earnings_declining(qis: Any) -> bool | None:
        if qis is None or getattr(qis, "empty", True):
            return None
        for label in ("Diluted EPS", "Basic EPS", "Net Income"):
            if label in qis.index:
                row = qis.loc[label].dropna()
                if len(row) >= 3:
                    return float(row.iloc[0]) < float(row.iloc[2])
        return None

    @staticmethod
    def _dividend_growth_5y_pct(divs: Any) -> float | None:
        if divs is None or getattr(divs, "empty", True):
            return None
        cutoff = datetime.now(UTC) - timedelta(days=365 * 5)
        try:
            divs_idx = divs.index
            tz = getattr(divs_idx, "tz", None)
            cutoff_local = cutoff if tz is None else cutoff.astimezone(tz)
            recent = divs[divs.index >= cutoff_local]
        except Exception:
            return None
        if len(recent) < 4:
            return None
        try:
            first = float(recent.iloc[0])
            last = float(recent.iloc[-1])
            if first <= 0:
                return None
            return (last - first) / first * 100.0
        except (TypeError, ValueError):
            return None

    # -------------------------------------------------------------------- news
    async def get_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 14,
    ) -> list[NewsItem]:
        cache_key = f"yahoo:news:{market}:{ticker}:{lookback_days}"
        cached = await self.cache.get(cache_key)
        if cached:
            import json

            return [NewsItem.model_validate(n) for n in json.loads(cached)]

        await self.rate_limiter.acquire()
        symbol = self._normalize_ticker(ticker, market)
        raw = await asyncio.to_thread(self._news_sync, symbol)
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        items: list[NewsItem] = []
        for n in raw:
            ts_epoch = n.get("providerPublishTime") or 0
            try:
                published_at = datetime.fromtimestamp(int(ts_epoch), tz=UTC)
            except (TypeError, ValueError, OSError):
                continue
            if published_at < cutoff:
                continue
            items.append(
                NewsItem(
                    ticker=ticker,
                    headline=str(n.get("title") or ""),
                    source=str(n.get("publisher") or "yahoo"),
                    url=str(n.get("link") or ""),
                    published_at=published_at,
                    sentiment_score=None,
                    summary=None,
                )
            )

        import json

        await self.cache.set(
            cache_key,
            json.dumps([i.model_dump(mode="json") for i in items], default=str),
            _NEWS_TTL,
        )
        return items

    @staticmethod
    def _news_sync(symbol: str) -> list[dict[str, Any]]:
        import yfinance as yf

        try:
            news = yf.Ticker(symbol).news or []
        except Exception:
            return []
        # Newer yfinance wraps each item in {"content": {...}}; flatten if so.
        flattened = []
        for n in news:
            if isinstance(n, dict) and "content" in n and isinstance(n["content"], dict):
                c = n["content"]
                flattened.append(
                    {
                        "title": c.get("title"),
                        "publisher": (c.get("provider") or {}).get("displayName"),
                        "link": (c.get("canonicalUrl") or {}).get("url"),
                        "providerPublishTime": _epoch(c.get("pubDate")),
                    }
                )
            else:
                flattened.append(n)
        return flattened

    # ------------------------------------------- raw symbol fetch (indices)
    async def get_index_history(
        self, symbol: str, days: int = 100
    ) -> list[OHLCBar]:
        """Fetch OHLC for a raw yfinance symbol (^VIX, ^GSPC, XLK, ^NSEI, …).

        Bypasses the ticker normalization used for equities.
        """
        cache_key = f"yahoo:idx:{symbol}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            import json

            return [OHLCBar.model_validate(b) for b in json.loads(cached)]

        await self.rate_limiter.acquire()
        end = date.today()
        start = end - timedelta(days=days)
        rows = await asyncio.to_thread(self._history_sync, symbol, "1d", start, end)
        bars = [
            OHLCBar(
                ticker=symbol,
                timestamp=ts,
                open=Decimal(str(o)),
                high=Decimal(str(h)),
                low=Decimal(str(l)),
                close=Decimal(str(c)),
                volume=int(v),
                interval="1d",
            )
            for ts, o, h, l, c, v in rows
        ]
        import json

        await self.cache.set(
            cache_key,
            json.dumps([b.model_dump(mode="json") for b in bars], default=str),
            _OHLC_TTL,
        )
        return bars

    # ----------------------------------------------------- corporate actions
    async def get_corporate_actions(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 365,
    ) -> list[CorporateAction]:
        await self.rate_limiter.acquire()
        symbol = self._normalize_ticker(ticker, market)
        return await asyncio.to_thread(self._actions_sync, ticker, symbol, lookback_days)

    @staticmethod
    def _actions_sync(
        ticker: str, symbol: str, lookback_days: int
    ) -> list[CorporateAction]:
        import yfinance as yf

        cutoff = datetime.now(UTC).date() - timedelta(days=lookback_days)
        out: list[CorporateAction] = []
        try:
            actions = yf.Ticker(symbol).actions
        except Exception:
            return out
        if actions is None or getattr(actions, "empty", True):
            return out
        for ts, row in actions.iterrows():
            d = ts.to_pydatetime().date() if hasattr(ts, "to_pydatetime") else ts
            if d < cutoff:
                continue
            div = float(row.get("Dividends") or 0)
            split = float(row.get("Stock Splits") or 0)
            if div > 0:
                out.append(
                    CorporateAction(
                        ticker=ticker,
                        action_type="dividend",
                        ex_date=d,
                        details={"amount": div},
                    )
                )
            if split > 0:
                out.append(
                    CorporateAction(
                        ticker=ticker,
                        action_type="split",
                        ex_date=d,
                        details={"ratio": split},
                    )
                )
        return out


def _epoch(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        # ISO8601 string (newer yfinance)
        s = str(value).replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except (TypeError, ValueError):
        return 0

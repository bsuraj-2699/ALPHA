"""Provider Protocol shared by every market-data integration (Upstox, Yahoo, etc.)."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from packages.shared.schemas import (
    CorporateAction,
    Fundamentals,
    Market,
    NewsItem,
    OHLCBar,
    Quote,
)

OHLCInterval = str


@runtime_checkable
class MarketDataProvider(Protocol):
    """Async interface every provider must satisfy.

    Implementations live in sibling modules (e.g. providers/upstox.py, providers/yahoo.py).
    The ContextBuilder fans out across a list of these to assemble the dict the
    RuleEvaluator expects.
    """

    name: str
    supported_markets: tuple[Market, ...]

    async def get_quote(self, ticker: str, market: Market) -> Quote: ...

    async def get_ohlc(
        self,
        ticker: str,
        market: Market,
        interval: OHLCInterval,
        start: date,
        end: date,
    ) -> list[OHLCBar]: ...

    async def get_fundamentals(self, ticker: str, market: Market) -> Fundamentals: ...

    async def get_news(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 14,
    ) -> list[NewsItem]: ...

    async def get_corporate_actions(
        self,
        ticker: str,
        market: Market,
        lookback_days: int = 365,
    ) -> list[CorporateAction]: ...

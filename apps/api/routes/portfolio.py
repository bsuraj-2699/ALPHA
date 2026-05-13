"""Portfolio endpoint.

Backed by an in-memory list on ``app.state.portfolio`` for now. A real
implementation would read from the broker / Postgres.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.deps import get_portfolio
from apps.api.models import PortfolioPosition, PortfolioResponse

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio_endpoint(
    portfolio: list[PortfolioPosition] = Depends(get_portfolio),
) -> PortfolioResponse:
    total = sum((p.current_value_usd or 0.0) for p in portfolio)
    return PortfolioResponse(positions=list(portfolio), total_value_usd=total)

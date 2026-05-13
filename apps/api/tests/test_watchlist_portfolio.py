"""Watchlist and portfolio endpoint tests."""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


async def test_watchlist_starts_empty(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


async def test_add_to_watchlist(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    add = await client.post(
        "/api/watchlist", json={"ticker": "AAPL", "market": "US"}
    )
    assert add.status_code == 201
    item = add.json()
    assert item["ticker"] == "AAPL"
    assert item["market"] == "US"

    listing = await client.get("/api/watchlist")
    assert len(listing.json()["items"]) == 1


async def test_watchlist_dedupes_same_ticker_market(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    body = {"ticker": "AAPL", "market": "US"}
    first = await client.post("/api/watchlist", json=body)
    second = await client.post("/api/watchlist", json=body)
    assert first.json() == second.json()  # same added_at, no duplicate

    listing = await client.get("/api/watchlist")
    assert len(listing.json()["items"]) == 1


async def test_watchlist_normalizes_ticker_case(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/watchlist", json={"ticker": "aapl", "market": "US"}
    )
    assert resp.status_code == 201
    assert resp.json()["ticker"] == "AAPL"


async def test_watchlist_rejects_bad_ticker(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.post(
        "/api/watchlist", json={"ticker": "???", "market": "US"}
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


async def test_portfolio_starts_empty(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"positions": [], "total_value_usd": 0.0}

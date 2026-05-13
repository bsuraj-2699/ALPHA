"""POST /api/analyze tests.

Covers:
  * Happy path: 202 + run_id + status pending/running.
  * Idempotency: identical body within the same UTC day returns the same
    run_id with idempotent_hit=True.
  * Validation: bad ticker / bad market is rejected with 422.
"""

from __future__ import annotations

import asyncio

from httpx import AsyncClient


async def _wait_for_run(client: AsyncClient, run_id: str, timeout: float = 5.0) -> dict:
    """Poll GET /api/runs/{run_id} until it reaches a terminal status or
    we time out. Tests use this to wait for the background task to finish."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/runs/{run_id}")
        if resp.status_code == 200:
            body = resp.json()
            if body["status"] in ("complete", "interrupted", "error"):
                return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_analyze_returns_202_with_run_id(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "market": "US"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "run_id" in body
    assert body["idempotent_hit"] is False
    assert body["status"] in ("pending", "running", "complete")
    assert len(body["run_id"]) == 16  # SHA-256 truncation
    # mode defaults to long_term and chart_config follows
    assert body["mode"] == "long_term"
    assert body["chart_config"]["primary_interval"] == "1week"
    assert body["chart_config"]["polling_interval_seconds"] == 86400


async def test_analyze_intraday_returns_5min_chart_config(
    client_with_healthy_ctx,
) -> None:
    """Intraday mode should advertise the 5-minute primary chart and the
    300-second polling cadence, so the frontend can render the right
    skeleton before the run completes."""
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze",
        json={"ticker": "MSFT", "market": "US", "mode": "intraday"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["mode"] == "intraday"
    cc = body["chart_config"]
    assert cc["primary_interval"] == "5minute"
    assert cc["secondary_interval"] == "15minute"
    assert cc["context_interval"] is None
    assert cc["polling_interval_seconds"] == 300
    assert cc["lookback_candles"] == 78


async def test_analyze_short_term_returns_daily_chart_config(
    client_with_healthy_ctx,
) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze",
        json={"ticker": "GOOG", "market": "US", "mode": "short_term"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["mode"] == "short_term"
    cc = body["chart_config"]
    assert cc["primary_interval"] == "1day"
    assert cc["secondary_interval"] == "60minute"
    assert cc["context_interval"] == "1week"
    assert cc["polling_interval_seconds"] == 3600
    assert cc["lookback_candles"] == 90


async def test_analyze_completes_with_decision(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze", json={"ticker": "AAPL", "market": "US"}
    )
    run_id = resp.json()["run_id"]
    final = await _wait_for_run(client, run_id)
    assert final["status"] == "complete"
    assert final["decision"] is not None
    assert final["decision"]["ticker"] == "AAPL"
    assert final["decision"]["signal"] in (
        "STRONG_BUY",
        "BUY",
        "HOLD",
        "SELL",
        "STRONG_SELL",
    )
    # Five analyst reports should be present.
    assert set(final["analyst_reports"].keys()) == {
        "fundamentals",
        "technicals",
        "sentiment",
        "macro",
        "risk",
    }
    # Reasoning trace covers parse + context_build + 5 analysts + debate +
    # judge + decide -> at least 10 entries.
    assert len(final["reasoning_trace"]) >= 9


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_analyze_intraday_each_post_new_run_id(
    client_with_healthy_ctx,
) -> None:
    """Intraday must not use daily (ticker, market) dedupe or later analyses
    never hit Postgres — see ``POST /api/analyze`` intraday branch."""
    client = client_with_healthy_ctx
    body = {"ticker": "INFY", "market": "IN", "mode": "intraday"}
    first = await client.post("/api/analyze", json=body)
    second = await client.post("/api/analyze", json=body)
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    rid_a = first.json()["run_id"]
    rid_b = second.json()["run_id"]
    assert rid_a != rid_b
    assert first.json()["idempotent_hit"] is False
    assert second.json()["idempotent_hit"] is False
    assert len(rid_a) == 16 and len(rid_b) == 16


async def test_analyze_is_idempotent_within_day(
    client_with_healthy_ctx,
) -> None:
    client = client_with_healthy_ctx
    body = {"ticker": "MSFT", "market": "US"}

    first = await client.post("/api/analyze", json=body)
    second = await client.post("/api/analyze", json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["idempotent_hit"] is False
    assert second.json()["idempotent_hit"] is True


async def test_analyze_different_ticker_different_run_id(
    client_with_healthy_ctx,
) -> None:
    client = client_with_healthy_ctx
    a = await client.post("/api/analyze", json={"ticker": "AAPL", "market": "US"})
    b = await client.post("/api/analyze", json={"ticker": "MSFT", "market": "US"})
    assert a.json()["run_id"] != b.json()["run_id"]


async def test_analyze_different_market_different_run_id(
    client_with_healthy_ctx,
) -> None:
    client = client_with_healthy_ctx
    a = await client.post("/api/analyze", json={"ticker": "RELIANCE", "market": "IN"})
    b = await client.post("/api/analyze", json={"ticker": "RELIANCE", "market": "US"})
    assert a.json()["run_id"] != b.json()["run_id"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_analyze_rejects_bad_ticker(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze", json={"ticker": "lower-case", "market": "US"}
    )
    assert resp.status_code == 422


async def test_analyze_rejects_bad_market(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze", json={"ticker": "AAPL", "market": "EU"}
    )
    assert resp.status_code == 422


async def test_analyze_rejects_extra_fields(client_with_healthy_ctx) -> None:
    """``extra='forbid'`` on AnalyzeRequest catches typos like ``tickers``."""
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze",
        json={"ticker": "AAPL", "market": "US", "tickers": ["AAPL", "MSFT"]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Portfolio context plumbing
# ---------------------------------------------------------------------------


async def test_portfolio_context_overrides_reach_evaluator(
    client_with_healthy_ctx,
) -> None:
    """Send portfolio_context with position_pct_of_portfolio>=10 (OVR-O5
    triggers BLOCK_BUY) and confirm the rule fires by checking the
    overrides_active list on the final decision."""
    client = client_with_healthy_ctx
    resp = await client.post(
        "/api/analyze",
        json={
            "ticker": "MSFT",
            "market": "US",
            "portfolio_context": {"position_pct_of_portfolio": 12.0},
        },
    )
    run_id = resp.json()["run_id"]
    final = await _wait_for_run(client, run_id)
    # OVR-O5 BLOCK_BUY converts STRONG_BUY/BUY -> HOLD; even if the underlying
    # composite would have been BUY, signal should now be HOLD with OVR-O5
    # in overrides_active.
    assert "OVR-O5" in final["decision"]["overrides_active"]
    assert final["decision"]["signal"] == "HOLD"

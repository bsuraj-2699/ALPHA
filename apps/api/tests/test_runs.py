"""GET /api/runs/{run_id}, /stream, POST /approve."""

from __future__ import annotations

import asyncio
import json

from httpx import AsyncClient


async def _wait_for_status(
    client: AsyncClient, run_id: str, target: set[str], timeout: float = 5.0
) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/runs/{run_id}")
        if resp.status_code == 200 and resp.json()["status"] in target:
            return resp.json()
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"run {run_id} never reached one of {target} within {timeout}s"
    )


# ---------------------------------------------------------------------------
# GET /runs/{id}
# ---------------------------------------------------------------------------


async def test_get_unknown_run_returns_404(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.get("/api/runs/does-not-exist")
    assert resp.status_code == 404


async def test_get_run_returns_full_state(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    started = await client.post(
        "/api/analyze", json={"ticker": "AAPL", "market": "US"}
    )
    run_id = started.json()["run_id"]
    final = await _wait_for_status(client, run_id, {"complete"})
    assert final["ticker"] == "AAPL"
    assert final["judgment"] is not None
    assert final["bull_case"] is not None
    assert final["bear_case"] is not None
    assert final["evaluation"] is not None


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


def _parse_sse(raw: str) -> list[dict]:
    """Parse a buffered SSE stream into a list of (event, data) dicts."""
    events: list[dict] = []
    current_event: str | None = None
    data_lines: list[str] = []
    for line in raw.splitlines():
        if line.startswith(":"):
            continue  # comment / keep-alive
        if line == "":
            if current_event is not None and data_lines:
                events.append(
                    {
                        "event": current_event,
                        "data": json.loads("\n".join(data_lines)),
                    }
                )
            current_event = None
            data_lines = []
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    return events


async def test_stream_emits_expected_event_types(client_with_healthy_ctx) -> None:
    client = client_with_healthy_ctx
    started = await client.post(
        "/api/analyze", json={"ticker": "AAPL", "market": "US"}
    )
    run_id = started.json()["run_id"]

    # Connect to the stream BEFORE the run finishes by racing it against a
    # quick reconnect; in practice the run is fast so subscribe-late is fine
    # too — we just need any stream-completion event.
    async with client.stream("GET", f"/api/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        chunks: list[str] = []
        async for chunk in resp.aiter_text():
            chunks.append(chunk)
            joined = "".join(chunks)
            if "event: decision" in joined or "event: error" in joined:
                # The terminal event arrived; SSE-Starlette will close the
                # generator on its own shortly. Break to inspect what we got.
                break

    events = _parse_sse("".join(chunks))
    types = [e["event"] for e in events]

    # We MUST see at least these. Other valid types: agent_start, thinking.
    assert "agent_complete" in types or "agent_start" in types, types

    # If the run reached the decide node we should see a decision event.
    final = await client.get(f"/api/runs/{run_id}")
    if final.json()["status"] == "complete":
        assert "decision" in types, f"expected 'decision' in stream, got {types}"


async def test_stream_404_on_unknown_run(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.get(
        "/api/runs/does-not-exist/stream"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Human-in-the-loop approve()
# ---------------------------------------------------------------------------


async def test_strong_signal_requires_approval(
    client_fraudco_interrupt_mode,
) -> None:
    """FRAUDCO triggers OVR-O1 -> STRONG_SELL -> human-review interrupt."""
    client = client_fraudco_interrupt_mode
    started = await client.post(
        "/api/analyze", json={"ticker": "FRAUDCO", "market": "US"}
    )
    run_id = started.json()["run_id"]
    paused = await _wait_for_status(client, run_id, {"interrupted"})
    assert paused["interrupt"] is not None
    assert paused["interrupt"]["signal"] == "STRONG_SELL"
    assert paused["decision"] is None


async def test_approve_finalizes_strong_signal(
    client_fraudco_interrupt_mode,
) -> None:
    client = client_fraudco_interrupt_mode
    started = await client.post(
        "/api/analyze", json={"ticker": "FRAUDCO", "market": "US"}
    )
    run_id = started.json()["run_id"]
    await _wait_for_status(client, run_id, {"interrupted"})

    resp = await client.post(
        f"/api/runs/{run_id}/approve",
        json={"response": "approve"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "complete"
    assert body["final_signal"] == "STRONG_SELL"

    detail = await client.get(f"/api/runs/{run_id}")
    assert detail.json()["decision"]["signal"] == "STRONG_SELL"
    assert "OVR-O1" in detail.json()["decision"]["overrides_active"]


async def test_reject_downgrades_strong_signal_to_hold(
    client_fraudco_interrupt_mode,
) -> None:
    client = client_fraudco_interrupt_mode
    started = await client.post(
        "/api/analyze", json={"ticker": "FRAUDCO", "market": "US"}
    )
    run_id = started.json()["run_id"]
    await _wait_for_status(client, run_id, {"interrupted"})

    resp = await client.post(
        f"/api/runs/{run_id}/approve",
        json={"response": "reject"},
    )
    assert resp.status_code == 202
    assert resp.json()["final_signal"] == "HOLD"

    detail = await client.get(f"/api/runs/{run_id}")
    decision = detail.json()["decision"]
    assert decision["signal"] == "HOLD"
    assert decision["position_size_pct"] == 0.0


async def test_approve_unknown_run_returns_404(
    client_fraudco_interrupt_mode,
) -> None:
    resp = await client_fraudco_interrupt_mode.post(
        "/api/runs/does-not-exist/approve",
        json={"response": "approve"},
    )
    assert resp.status_code == 404


async def test_approve_non_interrupted_run_returns_409(
    client_with_healthy_ctx,
) -> None:
    """A complete run can't be approved — only interrupted ones."""
    client = client_with_healthy_ctx
    started = await client.post(
        "/api/analyze", json={"ticker": "AAPL", "market": "US"}
    )
    run_id = started.json()["run_id"]
    await _wait_for_status(client, run_id, {"complete"})

    resp = await client.post(
        f"/api/runs/{run_id}/approve",
        json={"response": "approve"},
    )
    assert resp.status_code == 409

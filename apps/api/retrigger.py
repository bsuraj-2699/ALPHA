"""Redis pub/sub subscriber that turns ``retrigger:*`` events into runs.

The Upstox WebSocket adapter (:mod:`packages.data.providers.upstox_ws`)
publishes a JSON payload to ``retrigger:{symbol}`` whenever a tick crosses
the price-move / volume-spike thresholds (or the 5-minute fallback fires).
This module owns the receiving end: a long-lived background task that
psubscribes to the pattern and dispatches an intraday analysis run for
each event, with two safety rails:

  * **60-second completion cooldown** — if a run for the same symbol
    completed inside the last minute, the new tick is dropped. Prevents
    a flurry of ticks (or the schedule fallback colliding with a price
    move) from queueing back-to-back duplicate analyses.
  * **In-flight de-dup** — :meth:`RunManager.start_run` already collapses
    a duplicate ``run_id`` onto the existing record, so we get free
    protection against firing while a previous run is still executing.

Run IDs use ``retrigger-{symbol}-{epoch_seconds}`` so they don't collide
with the daily idempotency key issued by ``POST /api/analyze``; multiple
retriggers per day are by design.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from apps.api.runs import RunManager

logger = logging.getLogger(__name__)


RETRIGGER_PATTERN = "retrigger:*"
COOLDOWN_SECONDS = 60.0
RETRIGGER_MODE = "intraday"


def _ticker_from_channel(channel: str) -> str | None:
    """Strip the ``retrigger:`` prefix; return ``None`` for unrelated channels."""
    if not channel.startswith("retrigger:"):
        return None
    ticker = channel[len("retrigger:") :].strip()
    return ticker or None


class RetriggerSubscriber:
    """Background task subscribing to ``retrigger:*`` and dispatching runs."""

    def __init__(
        self,
        redis_client: Any,
        run_manager: RunManager,
        *,
        cooldown_seconds: float = COOLDOWN_SECONDS,
        mode: str = RETRIGGER_MODE,
    ) -> None:
        self._redis = redis_client
        self._run_manager = run_manager
        self._cooldown = cooldown_seconds
        self._mode = mode
        self._task: asyncio.Task[None] | None = None
        # Tracks the wall-clock dispatch time for tickers that have no
        # completed run yet — covers the case where a second tick arrives
        # while the first run is still executing.
        self._last_dispatched_at: dict[str, datetime] = {}

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self._run(), name="retrigger-subscriber")
        return self._task

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    # ----- internal -------------------------------------------------------

    async def _run(self) -> None:
        pubsub = self._redis.pubsub()
        try:
            await pubsub.psubscribe(RETRIGGER_PATTERN)
            logger.info("retrigger subscriber listening on %s", RETRIGGER_PATTERN)
            async for message in pubsub.listen():
                if message.get("type") != "pmessage":
                    continue
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("retrigger subscriber crashed")
            raise
        finally:
            try:
                await pubsub.punsubscribe(RETRIGGER_PATTERN)
                await pubsub.aclose()
            except Exception:
                pass

    async def _handle_message(self, message: dict[str, Any]) -> None:
        channel_raw = message.get("channel")
        if isinstance(channel_raw, bytes):
            channel_raw = channel_raw.decode("utf-8")
        if not isinstance(channel_raw, str):
            return
        ticker = _ticker_from_channel(channel_raw)
        if ticker is None:
            return

        payload_raw = message.get("data")
        if isinstance(payload_raw, bytes):
            payload_raw = payload_raw.decode("utf-8")
        try:
            payload = json.loads(payload_raw) if payload_raw else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}

        if not self._should_dispatch(ticker):
            return

        await self._dispatch(ticker, payload)

    def _should_dispatch(self, ticker: str) -> bool:
        now = datetime.now(timezone.utc)
        last_completed = self._run_manager.last_completed_for(ticker)
        if last_completed is not None:
            elapsed = (now - last_completed).total_seconds()
            if elapsed < self._cooldown:
                logger.debug(
                    "retrigger for %s suppressed: %.1fs since last completion",
                    ticker,
                    elapsed,
                )
                return False
        last_dispatched = self._last_dispatched_at.get(ticker)
        if last_dispatched is not None:
            elapsed = (now - last_dispatched).total_seconds()
            if elapsed < self._cooldown:
                logger.debug(
                    "retrigger for %s suppressed: dispatched %.1fs ago, no completion yet",
                    ticker,
                    elapsed,
                )
                return False
        return True

    async def _dispatch(self, ticker: str, payload: dict[str, Any]) -> None:
        run_id = f"retrigger-{ticker}-{int(time.time())}"
        self._last_dispatched_at[ticker] = datetime.now(timezone.utc)
        portfolio_context = {"retrigger_payload": payload} if payload else None
        try:
            await self._run_manager.start_run(
                run_id=run_id,
                ticker=ticker,
                market="IN",
                portfolio_context=portfolio_context,
                mode=self._mode,
            )
            logger.info(
                "retrigger dispatched run %s for %s (reason=%s)",
                run_id,
                ticker,
                payload.get("reason"),
            )
        except Exception:
            logger.exception("retrigger dispatch for %s failed", ticker)


__all__ = [
    "COOLDOWN_SECONDS",
    "RETRIGGER_MODE",
    "RETRIGGER_PATTERN",
    "RetriggerSubscriber",
]

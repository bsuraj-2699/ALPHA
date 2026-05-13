"""Background schedulers that turn bucket membership into runs.

Two long-lived asyncio tasks live here:

  * :class:`IntradayScheduler` — every ``interval_seconds`` (default 300)
    during NSE market hours (09:15–15:30 IST, Mon–Fri), dispatch a fresh
    ``intraday`` run for each ticker in the intraday bucket.
  * :class:`DailyScheduler` — once per Mon–Fri at the configured wall
    clock (default 10:00 IST), dispatch a fresh run for each ticker in
    the ``short_term`` and ``long_term`` buckets.

Both schedulers bypass the daily idempotency cache by minting their own
non-deterministic ``run_id`` (``intraday-RELIANCE-1714722900`` /
``short_term-RELIANCE-2026-05-04`` etc.). That mirrors the pattern the
retrigger subscriber already uses (:mod:`apps.api.retrigger`) so we do
not need any RunManager API changes.

Configuration is loaded from ``rules.json`` via
:func:`packages.shared.config.get_mode_schedule`. Operators can change
cadence and 10:00 → 09:30 by editing the JSON; no code edits or
restarts needed beyond the standard reload.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Iterable

try:  # zoneinfo is stdlib on 3.9+, but Windows needs tzdata
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

from apps.api.buckets import BucketStore
from apps.api.runs import RunManager
from packages.shared.config import (
    Mode,
    ModeSchedule,
    get_mode_schedule,
)

logger = logging.getLogger(__name__)


# Inputs we treat as "weekday: any business day" (matches rules.json).
_BUSINESS_WEEKDAY_TOKENS = frozenset({"mon-fri", "weekday", "weekdays"})


def _ist() -> Any:
    """Return ZoneInfo('Asia/Kolkata'), or UTC if zoneinfo unavailable."""
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo("Asia/Kolkata")
    except Exception:  # pragma: no cover
        return timezone.utc


def _is_business_day(now_local: datetime, weekdays: str) -> bool:
    """``Mon-Fri`` → ``weekday() < 5``; anything else → always True."""
    token = (weekdays or "").strip().lower()
    if token in _BUSINESS_WEEKDAY_TOKENS:
        return now_local.weekday() < 5
    return True


def _parse_hhmm(value: str) -> dt_time:
    """``"10:00"`` → ``datetime.time(10, 0)``. Falls back to 10:00 IST on garbage."""
    try:
        hour_s, minute_s = value.split(":", 1)
        return dt_time(int(hour_s), int(minute_s))
    except (AttributeError, ValueError):
        return dt_time(10, 0)


# ---------------------------------------------------------------------------
# IntradayScheduler — re-run every N seconds during NSE hours
# ---------------------------------------------------------------------------


# Hardcoded NSE session boundaries. ``rules.json`` carries the same
# values for documentation but the scheduler treats them as constants
# here so that a missing/garbled spec still produces a safe schedule.
_INTRADAY_SESSION_OPEN = dt_time(9, 15)
_INTRADAY_SESSION_CLOSE = dt_time(15, 30)


class IntradayScheduler:
    """Dispatch ``intraday`` runs for every bucket ticker every N seconds."""

    MODE: Mode = "intraday"

    def __init__(
        self,
        bucket_store: BucketStore,
        run_manager: RunManager,
        *,
        market: str = "IN",
        interval_seconds: int | None = None,
        sleep: Any = None,
    ) -> None:
        self._buckets = bucket_store
        self._runs = run_manager
        self._market = market
        # Allow tests to inject ``asyncio.sleep`` replacements.
        self._sleep = sleep or asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        schedule = get_mode_schedule(self.MODE)
        self._schedule: ModeSchedule = schedule
        self._interval = (
            interval_seconds
            if interval_seconds is not None
            else (schedule.interval_seconds or 300)
        )

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="intraday-scheduler")
        return self._task

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        logger.info(
            "intraday scheduler started (interval=%ds, market=%s, weekdays=%s)",
            self._interval, self._market, self._schedule.weekdays,
        )
        while not self._stopped.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("intraday scheduler tick failed")
            try:
                await self._sleep(self._interval)
            except asyncio.CancelledError:
                raise

    async def _tick(self) -> None:
        if not self._is_session_open():
            return
        tickers = await self._buckets.list("intraday")
        if not tickers:
            return
        await _dispatch_runs(
            run_manager=self._runs,
            tickers=tickers,
            mode=self.MODE,
            market=self._market,
            run_id_factory=lambda t: f"intraday-{t}-{int(time.time())}",
            tag="intraday-scheduler",
        )

    def _is_session_open(self, now: datetime | None = None) -> bool:
        local = (now or datetime.now(_ist())).astimezone(_ist())
        if not _is_business_day(local, self._schedule.weekdays):
            return False
        clock = local.time()
        return _INTRADAY_SESSION_OPEN <= clock <= _INTRADAY_SESSION_CLOSE


# ---------------------------------------------------------------------------
# DailyScheduler — fire short_term + long_term once per business day at HH:MM
# ---------------------------------------------------------------------------


class DailyScheduler:
    """Fire ``short_term`` + ``long_term`` runs once per business day."""

    MODES: tuple[Mode, ...] = ("short_term", "long_term")

    def __init__(
        self,
        bucket_store: BucketStore,
        run_manager: RunManager,
        *,
        market: str = "IN",
        sleep: Any = None,
    ) -> None:
        self._buckets = bucket_store
        self._runs = run_manager
        self._market = market
        self._sleep = sleep or asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        # Both modes use the same daily schedule (10:00 IST in v2.0.1) —
        # we read ``short_term`` because ``long_term`` mirrors it; if that
        # ever changes we'd want one task per mode instead of one shared.
        self._schedule = get_mode_schedule("short_term")
        self._target_time = _parse_hhmm(self._schedule.time_hhmm or "10:00")
        self._tz = _ist()

    def start(self) -> asyncio.Task[None]:
        if self._task is not None and not self._task.done():
            return self._task
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="daily-scheduler")
        return self._task

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        logger.info(
            "daily scheduler started (target=%s %s, weekdays=%s, modes=%s)",
            self._target_time.isoformat(),
            getattr(self._tz, "key", "UTC"),
            self._schedule.weekdays,
            list(self.MODES),
        )
        while not self._stopped.is_set():
            sleep_s = self._seconds_until_next_run()
            try:
                await self._sleep(sleep_s)
            except asyncio.CancelledError:
                raise
            try:
                await self._fire()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("daily scheduler fire failed")

    def _seconds_until_next_run(self, now: datetime | None = None) -> float:
        """Wall-clock seconds until the next allowed business-day fire."""
        current = (now or datetime.now(self._tz)).astimezone(self._tz)
        candidate = current.replace(
            hour=self._target_time.hour,
            minute=self._target_time.minute,
            second=0,
            microsecond=0,
        )
        # Roll forward at least one second so we don't double-fire when
        # we wake up exactly at the target wall clock.
        if candidate <= current:
            candidate = candidate + timedelta(days=1)
        # Skip Sat (5) and Sun (6) when weekdays asks for business days.
        for _ in range(7):
            if _is_business_day(candidate, self._schedule.weekdays):
                break
            candidate = candidate + timedelta(days=1)
        delta = (candidate - current).total_seconds()
        return max(1.0, delta)

    async def _fire(self) -> None:
        run_date = datetime.now(self._tz).date().isoformat()
        for mode in self.MODES:
            tickers = await self._buckets.list(mode)
            if not tickers:
                continue
            await _dispatch_runs(
                run_manager=self._runs,
                tickers=tickers,
                mode=mode,
                market=self._market,
                run_id_factory=lambda t, m=mode: f"{m}-{t}-{run_date}",
                tag="daily-scheduler",
            )


# ---------------------------------------------------------------------------
# Shared dispatch helper
# ---------------------------------------------------------------------------


async def _dispatch_runs(
    *,
    run_manager: RunManager,
    tickers: Iterable[str],
    mode: Mode,
    market: str,
    run_id_factory: Any,
    tag: str,
) -> None:
    """Start one run per ticker, swallowing per-ticker errors.

    The RunManager already de-dupes runs on identical ``run_id``, so a
    daily scheduler that fires twice on the same date is idempotent for
    free. Intraday's epoch-based id never collides naturally.
    """
    for ticker in tickers:
        run_id = run_id_factory(ticker)
        try:
            await run_manager.start_run(
                run_id=run_id,
                ticker=ticker,
                market=market,
                mode=mode,
            )
            logger.info(
                "%s dispatched %s for %s (mode=%s)",
                tag, run_id, ticker, mode,
            )
        except Exception:
            logger.exception(
                "%s failed to dispatch run for %s (mode=%s)",
                tag, ticker, mode,
            )


__all__ = ["DailyScheduler", "IntradayScheduler"]

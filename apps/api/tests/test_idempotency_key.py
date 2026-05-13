"""Unit tests for :func:`apps.api.idempotency.make_idempotency_key`."""

from __future__ import annotations

from datetime import datetime, timezone

from apps.api.idempotency import make_idempotency_key


def test_key_differs_by_mode_same_day() -> None:
    fixed = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    lt = make_idempotency_key("INFY", "IN", mode="long_term", now=fixed)
    st = make_idempotency_key("INFY", "IN", mode="short_term", now=fixed)
    assert lt != st


def test_key_stable_for_identical_inputs() -> None:
    fixed = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    a = make_idempotency_key("SBIN", "IN", mode="long_term", now=fixed)
    b = make_idempotency_key("SBIN", "IN", mode="long_term", now=fixed)
    assert a == b

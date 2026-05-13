"""Test fixtures for the data package.

Most tests in this directory hit live APIs and are gated behind the
`integration` marker. Run them with `pytest -m integration` and the
right environment variables set.
"""

from __future__ import annotations

import os

import pytest


def _env_present(*names: str) -> bool:
    return all(os.getenv(n) for n in names)


def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    """Skip integration tests if their required env vars are absent.

    Each test can declare what it needs via a `requires_env` marker, e.g.:
        @pytest.mark.integration
        @pytest.mark.requires_env("UPSTOX_API_KEY", "UPSTOX_ACCESS_TOKEN")
    """
    for item in items:
        req = item.get_closest_marker("requires_env")
        if req and not _env_present(*req.args):
            item.add_marker(
                pytest.mark.skip(reason=f"missing env vars: {', '.join(req.args)}")
            )


# Track which optional deps are available so tests can self-skip cleanly.
@pytest.fixture(scope="session")
def yfinance_available() -> bool:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture(scope="session")
def upstox_available() -> bool:
    """Upstox uses plain HTTP (no SDK) — gate on credentials only."""
    return _env_present("UPSTOX_API_KEY", "UPSTOX_API_SECRET")

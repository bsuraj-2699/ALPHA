"""Price route returns an explicit 'unavailable' state (never synthetic)."""

from __future__ import annotations

from types import SimpleNamespace

from apps.api.routes import price


async def test_no_providers_yields_unavailable_not_synthetic(monkeypatch):
    # No provider returns OHLC -> the route must surface an empty, unavailable
    # chart rather than fabricating candles.
    monkeypatch.setattr(price, "_get_or_build_providers", lambda request, market: [])

    resp = await price.get_price(
        request=SimpleNamespace(),
        ticker="ZZZZ",
        market="IN",
        interval="1d",
        lookback_days=200,
    )

    assert resp.source == "unavailable"
    assert resp.bars == []
    assert resp.stale is True


def test_synthetic_bars_helper_removed():
    assert not hasattr(price, "_synthetic_bars")

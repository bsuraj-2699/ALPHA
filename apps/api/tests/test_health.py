"""GET /health tests.

Default test config has no DATABASE_URL / REDIS_URL / QDRANT_URL set, so we
expect every service to report ``not_configured`` and the overall status to
be ``ok`` (dev posture is fully in-memory, all-green).
"""

from __future__ import annotations


async def test_health_reports_all_services_when_unconfigured(
    client_with_healthy_ctx,
) -> None:
    resp = await client_with_healthy_ctx.get("/health")
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "ok"
    assert set(body["services"].keys()) == {"postgres", "redis", "qdrant"}
    for name, svc in body["services"].items():
        # Without any URL configured we should never report 'down'.
        assert svc["status"] in ("not_configured", "ok"), (
            f"{name} reported {svc['status']}"
        )


async def test_health_includes_version(client_with_healthy_ctx) -> None:
    resp = await client_with_healthy_ctx.get("/health")
    assert "version" in resp.json()

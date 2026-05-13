"""Upstox OAuth2 token refresh.

Upstox access tokens expire daily at 03:30 UTC (09:00 IST). This module runs
the OAuth2 authorization-code exchange and writes the resulting token to
Redis under the well-known key ``upstox:access_token`` so every consumer
(REST provider, WebSocket feed) can pick it up without a process restart.

The authorization code itself comes from a one-time browser flow (login at
https://api.upstox.com/v2/login/authorization/dialog) and is provided as
``UPSTOX_AUTH_CODE`` in the environment. After the first refresh, callers
can stash a long-lived refresh token in ``UPSTOX_REFRESH_TOKEN`` and this
module will use the refresh-token grant instead.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from packages.data.providers.cache import RedisCache

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
_REDIS_KEY = "upstox:access_token"
# Tokens expire at 03:30 UTC the next day; the spec says we run the refresh
# at 09:00 IST (≈03:30 UTC). Cache TTL is 22h to leave a safety margin.
_TOKEN_TTL = 22 * 60 * 60


async def refresh_access_token(cache: RedisCache | None = None) -> str | None:
    """Exchange the configured grant for a fresh access token and cache it.

    Returns the new token on success, or ``None`` if any of the required
    config is missing or the exchange fails. Failure is logged but never
    raised — the caller (a startup hook / scheduler) should keep running.
    """
    api_key = os.getenv("UPSTOX_API_KEY")
    api_secret = os.getenv("UPSTOX_API_SECRET")
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "http://localhost")
    auth_code = os.getenv("UPSTOX_AUTH_CODE")
    refresh_token = os.getenv("UPSTOX_REFRESH_TOKEN")

    if not api_key or not api_secret:
        logger.warning("upstox refresh skipped — UPSTOX_API_KEY/SECRET missing")
        return None
    if not (auth_code or refresh_token):
        logger.warning(
            "upstox refresh skipped — neither UPSTOX_AUTH_CODE nor UPSTOX_REFRESH_TOKEN set"
        )
        return None

    if refresh_token:
        payload = {
            "client_id": api_key,
            "client_secret": api_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    else:
        payload = {
            "client_id": api_key,
            "client_secret": api_secret,
            "code": auth_code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_TOKEN_URL, data=payload, headers=headers)
    except (httpx.HTTPError, OSError) as e:
        logger.warning("upstox token exchange failed: %s", e)
        return None
    if resp.status_code != 200:
        logger.warning(
            "upstox token exchange status=%d body=%s",
            resp.status_code,
            resp.text[:200],
        )
        return None

    body: dict[str, Any] = resp.json()
    token = body.get("access_token")
    if not token:
        logger.warning("upstox token exchange returned no access_token: %s", body)
        return None

    cache = cache if cache is not None else RedisCache()
    await cache.set(_REDIS_KEY, token, _TOKEN_TTL)
    logger.info("upstox access token refreshed")
    return token


__all__ = ["refresh_access_token"]

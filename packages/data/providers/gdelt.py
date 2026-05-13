"""GDELT 2.0 sentiment adapter.

GDELT exposes a free public DOC API; no key required. We hit ArtList mode for
the rolling 14-day window and aggregate per-article tone scores.

Tone scale: GDELT reports a -100 to +100 tone for each article (most fall in
[-10, +10]). We normalize to [-1, +1] by clamping at ±10 and dividing by 10.

Outputs:
    news_sentiment_14d_avg     — float in [-1, +1]
    negative_news_volume_spike — bool: today's negative-tone count > 2× the
                                 14-day trailing daily average

Endpoint:
    https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=ArtList&format=json

Limits: GDELT recommends ≤1 req/sec from a single IP; we cap at 5 req/min to
be polite — this provider only fires once per build.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

import httpx

from packages.data.providers.cache import RedisCache
from packages.data.providers.rate_limit import RateLimiter
from packages.shared.schemas import Market

logger = logging.getLogger(__name__)

_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 10.0
_TTL = 60 * 60  # 1h
_NEG_THRESHOLD = -2.0  # tone < -2 counts as a "negative" article
_SPIKE_RATIO = 2.0


class GDELTProvider:
    name = "gdelt"
    supported_markets: tuple[Market, ...] = ("IN", "US")

    def __init__(
        self,
        cache: RedisCache | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.cache = cache if cache is not None else RedisCache()
        self.rate_limiter = rate_limiter or RateLimiter.per_minute(5)

    @staticmethod
    def _query_for(ticker: str, market: Market) -> str:
        # Strip exchange suffix; GDELT searches free text. Quote the symbol so
        # we don't get false positives from short common words.
        bare = ticker.split(".")[0]
        return f'"{bare}"'

    async def get_sentiment_block(self, ticker: str, market: Market) -> dict[str, Any]:
        cache_key = f"gdelt:{ticker}:{market}"
        cached = await self.cache.get(cache_key)
        if cached:
            import json

            return json.loads(cached)

        await self.rate_limiter.acquire()
        params = {
            "query": self._query_for(ticker, market),
            "mode": "ArtList",
            "maxrecords": "250",
            "timespan": "14d",
            "format": "json",
            "sort": "DateDesc",
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_BASE, params=params)
        except (httpx.HTTPError, OSError) as e:
            logger.warning("gdelt failed: %s", e)
            # Neutral fallback so sentiment rules don't all skip.
            return {
                "news_sentiment_14d_avg": 0.0,
                "negative_news_volume_spike": False,
            }
        if resp.status_code != 200:
            logger.warning("gdelt status=%d", resp.status_code)
            # Common case is rate limiting (429). Degrade to neutral rather than
            # returning empty (which would cause sentiment rules to skip).
            return {
                "news_sentiment_14d_avg": 0.0,
                "negative_news_volume_spike": False,
            }

        # GDELT sometimes returns text/plain with leading whitespace; be lenient.
        try:
            payload = resp.json()
        except ValueError:
            logger.warning("gdelt non-JSON response")
            return {}

        articles = payload.get("articles") or []
        if not articles:
            return {
                "news_sentiment_14d_avg": 0.0,
                "negative_news_volume_spike": False,
            }

        tones: list[float] = []
        per_day_neg: dict[str, int] = {}
        today_str = datetime.now(UTC).strftime("%Y%m%d")
        for art in articles:
            tone_raw = art.get("tone")
            if tone_raw is None:
                continue
            try:
                tone = float(tone_raw)
            except (TypeError, ValueError):
                continue
            tones.append(tone)
            seendate = str(art.get("seendate") or "")[:8]
            if seendate and tone < _NEG_THRESHOLD:
                per_day_neg[seendate] = per_day_neg.get(seendate, 0) + 1

        if not tones:
            return {
                "news_sentiment_14d_avg": 0.0,
                "negative_news_volume_spike": False,
            }

        avg_tone = mean(tones)
        normalized = max(-1.0, min(1.0, avg_tone / 10.0))

        today_neg = per_day_neg.get(today_str, 0)
        prior_days = [v for d, v in per_day_neg.items() if d != today_str]
        prior_avg = mean(prior_days) if prior_days else 0.0
        spike = today_neg > _SPIKE_RATIO * prior_avg and today_neg >= 3

        out = {
            "news_sentiment_14d_avg": normalized,
            "negative_news_volume_spike": bool(spike),
        }
        import json

        await self.cache.set(cache_key, json.dumps(out), _TTL)
        return out

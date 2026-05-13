"""Hybrid retriever: dense (Qdrant) ⊕ BM25 → RRF → optional Cohere rerank.

Reciprocal Rank Fusion (Cormack et al. 2009) avoids any score-normalization
headache between the two systems. We fix `k=60` per the original paper; that
constant has held up well across IR benchmarks.

Filtering happens twice — once at the Qdrant payload level, once at the BM25
metadata level — so a `ticker=AAPL` query never has to inspect SEC filings
for unrelated tickers.

Cohere rerank-3 is optional. If `COHERE_API_KEY` is unset we skip reranking
and return the RRF order directly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

from packages.rag.bm25 import BM25Index
from packages.rag.embeddings import Embedder, get_default_embedder
from packages.rag.store import Chunk, SearchHit, VectorStore

logger = logging.getLogger(__name__)


_RRF_K = 60


@dataclass
class RetrievalResult:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]
    sources: list[str]  # which legs surfaced this doc, e.g. ["bm25", "dense"]


class HybridRetriever:
    def __init__(
        self,
        store: VectorStore,
        bm25: BM25Index,
        embedder: Embedder | None = None,
        cohere_api_key: str | None = None,
    ) -> None:
        self.store = store
        self.bm25 = bm25
        self.embedder = embedder or get_default_embedder()
        self.cohere_api_key = cohere_api_key or os.getenv("COHERE_API_KEY")

    async def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        oversample: int = 5,
        rerank: bool = True,
    ) -> list[RetrievalResult]:
        # Pull `limit * oversample` from each leg so RRF has signal to fuse.
        fetch_n = limit * oversample
        dense_task = asyncio.create_task(self._dense(query, fetch_n, filters))
        bm25_task = asyncio.create_task(asyncio.to_thread(self.bm25.search, query, fetch_n, filters))

        dense_hits, bm25_hits = await asyncio.gather(dense_task, bm25_task)
        fused = _rrf_merge(dense_hits, bm25_hits, k=_RRF_K)

        if rerank and self.cohere_api_key:
            try:
                fused = await self._rerank(query, fused, limit)
            except Exception as e:
                logger.warning("cohere rerank failed: %s", e)
        return fused[:limit]

    async def _dense(
        self,
        query: str,
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[SearchHit]:
        vec = (await self.embedder.embed([query]))[0]
        return await asyncio.to_thread(self.store.search, vec, limit, filters)

    async def _rerank(
        self, query: str, candidates: list[RetrievalResult], top_n: int
    ) -> list[RetrievalResult]:
        import cohere

        client = cohere.Client(self.cohere_api_key)
        docs = [c.text for c in candidates]
        resp = await asyncio.to_thread(
            client.rerank,
            model="rerank-3",
            query=query,
            documents=docs,
            top_n=min(top_n, len(docs)),
        )
        # cohere.Client returns a result with .results: list[RerankResult{index, relevance_score}]
        results = getattr(resp, "results", None) or resp
        out: list[RetrievalResult] = []
        for r in results:
            idx = getattr(r, "index", None)
            if idx is None or idx >= len(candidates):
                continue
            base = candidates[idx]
            out.append(
                RetrievalResult(
                    id=base.id,
                    score=float(getattr(r, "relevance_score", base.score)),
                    text=base.text,
                    metadata=base.metadata,
                    sources=[*base.sources, "cohere"],
                )
            )
        return out


# ---------------------------------------------------------------------------
# RRF
# ---------------------------------------------------------------------------

def _rrf_merge(
    dense: list[SearchHit],
    bm25: list[tuple[Chunk, float]],
    k: int = _RRF_K,
) -> list[RetrievalResult]:
    """Fuse two ranked lists with reciprocal rank fusion."""
    scores: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    payloads: dict[str, RetrievalResult] = {}

    for rank, hit in enumerate(dense):
        scores[hit.id] = scores.get(hit.id, 0.0) + 1 / (k + rank + 1)
        sources.setdefault(hit.id, []).append("dense")
        payloads.setdefault(
            hit.id,
            RetrievalResult(id=hit.id, score=0.0, text=hit.text, metadata=hit.metadata, sources=[]),
        )

    for rank, (chunk, _) in enumerate(bm25):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (k + rank + 1)
        sources.setdefault(chunk.id, []).append("bm25")
        payloads.setdefault(
            chunk.id,
            RetrievalResult(
                id=chunk.id, score=0.0, text=chunk.text, metadata=chunk.metadata, sources=[]
            ),
        )

    fused: list[RetrievalResult] = []
    for cid, s in sorted(scores.items(), key=lambda x: -x[1]):
        p = payloads[cid]
        fused.append(
            RetrievalResult(id=p.id, score=s, text=p.text, metadata=p.metadata, sources=sources[cid])
        )
    return fused

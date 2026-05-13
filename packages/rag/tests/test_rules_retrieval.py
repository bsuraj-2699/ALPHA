"""Round-trip test: ingest rules.json into an in-memory Qdrant + BM25 index,
then query for an FCF-related question and assert FUND-005 ranks in top 3.

Failing this test means the rule chunker is dropping signal (rule_id, name,
or rationale aren't making it into the indexed text) — the retriever itself
is straightforward.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# Skip the whole module if the RAG dependency stack isn't installed.
pytest.importorskip("qdrant_client")
pytest.importorskip("rank_bm25")
pytest.importorskip("fastembed")


RULES_PATH = Path(__file__).resolve().parents[2] / "core" / "rules.json"


@pytest.fixture(scope="module")
def event_loop():  # type: ignore[no-untyped-def]
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def ingested_retriever(event_loop):  # type: ignore[no-untyped-def]
    from packages.rag.bm25 import BM25Index
    from packages.rag.chunkers import chunk_rules
    from packages.rag.embeddings import FastEmbedEmbedder
    from packages.rag.retriever import HybridRetriever
    from packages.rag.store import VectorStore

    embedder = FastEmbedEmbedder("BAAI/bge-small-en-v1.5")
    store = VectorStore("test_rules", in_memory=True)
    bm25 = BM25Index()

    chunks = chunk_rules(RULES_PATH)
    assert len(chunks) >= 35, "rules.json should yield ≥35 chunks (32 rules + 5 overrides)"

    async def _ingest() -> None:
        store.ensure_collection(embedder.dim)
        vectors = await embedder.embed([c.text for c in chunks])
        store.upsert(chunks, vectors)
        bm25.add(chunks)

    event_loop.run_until_complete(_ingest())
    return HybridRetriever(store=store, bm25=bm25, embedder=embedder)


def test_rule_chunks_carry_rule_id_metadata():
    from packages.rag.chunkers import chunk_rules

    chunks = chunk_rules(RULES_PATH)
    # Every chunk has rule_id metadata + the id is in the text body
    fcf = next(c for c in chunks if c.metadata.get("rule_id") == "FUND-005")
    assert "FUND-005" in fcf.text
    assert "Free Cash Flow" in fcf.text
    assert "fcf_yield_pct" in fcf.text  # condition variable made it in


def test_fcf_query_returns_fund005_in_top3(ingested_retriever, event_loop):  # type: ignore[no-untyped-def]
    query = "What's the BUY threshold for FCF yield?"
    results = event_loop.run_until_complete(ingested_retriever.search(query, limit=3))

    top_ids = [r.metadata.get("rule_id") for r in results]
    assert "FUND-005" in top_ids, (
        f"FUND-005 (FCF rule) should be in top 3 for query {query!r}, got {top_ids}"
    )


def test_metadata_filter_restricts_to_overrides(ingested_retriever, event_loop):  # type: ignore[no-untyped-def]
    """A category=override pre-filter should only surface OVR-* rules."""
    query = "fraud or accounting restatement"
    results = event_loop.run_until_complete(
        ingested_retriever.search(query, limit=3, filters={"category": "override"})
    )
    assert results, "expected at least one override hit"
    for r in results:
        assert r.metadata.get("rule_id", "").startswith("OVR-"), (
            f"filter leaked: {r.metadata.get('rule_id')}"
        )

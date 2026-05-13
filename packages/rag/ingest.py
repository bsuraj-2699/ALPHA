"""Ingestion pipeline: chunks → embeddings → Qdrant + BM25 keyword index.

CLI
---
    python -m packages.rag.ingest --rules
    python -m packages.rag.ingest --filing path/to/10k.pdf --ticker AAPL --fiscal-year 2024
    python -m packages.rag.ingest --transcript path/to/q3.txt --ticker AAPL --quarter Q3-2024

Both indices share a stable chunk-id space (e.g. `rule:FUND-005`,
`filing:AAPL:2024:risk_factors:3`) so re-ingestion is idempotent — Qdrant
upsert overwrites, BM25 rebuilds on save.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from packages.rag.bm25 import BM25Index
from packages.rag.chunkers import chunk_filing, chunk_rules, chunk_transcript
from packages.rag.embeddings import Embedder, get_default_embedder
from packages.rag.store import Chunk, VectorStore

logger = logging.getLogger(__name__)


DEFAULT_COLLECTION = os.getenv("RAG_COLLECTION", "fin_rag")
DEFAULT_BM25_PATH = Path(os.getenv("RAG_BM25_PATH", ".rag/bm25.json"))


class Ingestor:
    def __init__(
        self,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        bm25_path: Path | None = None,
    ) -> None:
        self.embedder = embedder or get_default_embedder()
        self.store = store or VectorStore(DEFAULT_COLLECTION)
        self.bm25_path = bm25_path or DEFAULT_BM25_PATH
        self.bm25 = BM25Index.load(self.bm25_path) if self.bm25_path.exists() else BM25Index()

    async def ingest(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        self.store.ensure_collection(self.embedder.dim)
        vectors = await self.embedder.embed([c.text for c in chunks])
        self.store.upsert(chunks, vectors)

        # Update BM25: drop any chunk-ids we're re-ingesting, then add fresh.
        new_ids = {c.id for c in chunks}
        self.bm25.chunks = [c for c in self.bm25.chunks if c.id not in new_ids]
        self.bm25.add(chunks)
        self.bm25.save(self.bm25_path)
        return len(chunks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> int:
    ingestor = Ingestor()
    total = 0

    if args.rules:
        rules_path = Path(args.rules_path)
        chunks = chunk_rules(rules_path)
        n = await ingestor.ingest(chunks)
        print(f"Ingested {n} rule chunks from {rules_path}")
        total += n

    if args.filing:
        if not args.ticker or not args.fiscal_year:
            raise SystemExit("--filing requires --ticker and --fiscal-year")
        chunks = chunk_filing(Path(args.filing), args.ticker, args.fiscal_year)
        n = await ingestor.ingest(chunks)
        print(f"Ingested {n} filing chunks from {args.filing}")
        total += n

    if args.transcript:
        if not args.ticker or not args.quarter:
            raise SystemExit("--transcript requires --ticker and --quarter")
        chunks = chunk_transcript(Path(args.transcript), args.ticker, args.quarter)
        n = await ingestor.ingest(chunks)
        print(f"Ingested {n} transcript chunks from {args.transcript}")
        total += n

    print(f"Total chunks ingested: {total}")
    print(f"BM25 index: {ingestor.bm25_path}")
    print(f"Vectors in collection '{ingestor.store.collection}': {ingestor.store.count()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG ingestion CLI")
    parser.add_argument("--rules", action="store_true", help="ingest rules.json")
    parser.add_argument(
        "--rules-path",
        default=str(Path(__file__).resolve().parents[1] / "core" / "rules.json"),
        help="path to rules.json (default: packages/core/rules.json)",
    )
    parser.add_argument("--filing", help="path to a 10-K/annual report PDF")
    parser.add_argument("--transcript", help="path to an earnings call transcript (text)")
    parser.add_argument("--ticker", help="ticker symbol for filing/transcript")
    parser.add_argument("--fiscal-year", help="fiscal year for filing")
    parser.add_argument("--quarter", help="quarter label for transcript (e.g. Q3-2024)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not (args.rules or args.filing or args.transcript):
        parser.print_help()
        return 1
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

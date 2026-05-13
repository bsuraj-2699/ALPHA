"""BM25 keyword index used as the lexical leg of hybrid retrieval.

Persisted to a single JSON file alongside the Qdrant collection.

Tokenization is intentionally lightweight: lowercase + alnum split + stem-free.
Heavier tokenizers (Porter, English stopwords) hurt finance vocabulary
recall more than they help — "EPS", "P/E", "FCF" are exactly the terms that
matter and standard stopword lists strip them.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from packages.rag.store import Chunk

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class BM25Index:
    """In-memory BM25 over a list of chunks."""

    chunks: list[Chunk] = field(default_factory=list)
    _bm25: Any | None = None

    def add(self, chunks: list[Chunk]) -> None:
        self.chunks.extend(chunks)
        self._rebuild()

    def _rebuild(self) -> None:
        from rank_bm25 import BM25Okapi

        if not self.chunks:
            self._bm25 = None
            return
        tokenized = [tokenize(c.text) for c in self.chunks]
        self._bm25 = BM25Okapi(tokenized)

    def search(
        self,
        query: str,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[Chunk, float]]:
        if not self._bm25 or not self.chunks:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        indices = sorted(range(len(scores)), key=lambda i: -scores[i])

        out: list[tuple[Chunk, float]] = []
        for idx in indices:
            if scores[idx] <= 0:
                continue
            chunk = self.chunks[idx]
            if filters and not _matches(chunk.metadata, filters):
                continue
            out.append((chunk, float(scores[idx])))
            if len(out) >= limit:
                break
        return out

    # --------------------------------------------------------------- persist
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {"id": c.id, "text": c.text, "metadata": c.metadata}
            for c in self.chunks
        ]
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> BM25Index:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        idx = cls(
            chunks=[
                Chunk(id=d["id"], text=d["text"], metadata=d.get("metadata", {}))
                for d in data
            ]
        )
        idx._rebuild()
        return idx


def _matches(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for k, v in filters.items():
        meta_v = metadata.get(k)
        if isinstance(v, list):
            if isinstance(meta_v, list):
                if not set(meta_v).intersection(v):
                    return False
            elif meta_v not in v:
                return False
        else:
            if isinstance(meta_v, list):
                if v not in meta_v:
                    return False
            elif meta_v != v:
                return False
    return True

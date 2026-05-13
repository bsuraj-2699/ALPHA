"""Qdrant wrapper — collection management, upsert, filtered search.

Two modes:
    * Local in-memory (`QdrantClient(":memory:")`) — used for tests.
    * Remote (`QDRANT_URL` env var) — used in dev/prod, backed by the
      docker-compose service in infra/.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("a4d1b9c2-3f00-4f3a-bc45-9d8e7f6a5b4c")


@dataclass
class Chunk:
    """A unit of indexable text + payload metadata."""

    id: str           # human-readable id; goes into payload, not Qdrant's point id
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def point_id(self) -> str:
        return str(uuid.uuid5(_NAMESPACE, self.id))


@dataclass
class SearchHit:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStore:
    """Thin Qdrant facade. Distance is COSINE; vector size is taken from the
    embedder at collection-creation time."""

    def __init__(
        self,
        collection: str,
        url: str | None = None,
        in_memory: bool = False,
    ) -> None:
        from qdrant_client import QdrantClient

        self.collection = collection
        if in_memory:
            self._client = QdrantClient(":memory:")
        else:
            url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
            self._client = QdrantClient(url=url)

    def ensure_collection(self, dim: int) -> None:
        from qdrant_client.http.exceptions import UnexpectedResponse
        from qdrant_client.models import Distance, VectorParams

        try:
            self._client.get_collection(self.collection)
            return
        except (UnexpectedResponse, ValueError, Exception):
            pass
        self._client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        # Index commonly-filtered fields so payload pre-filters stay fast.
        for field_name in ("doc_type", "ticker", "rule_id", "category"):
            try:
                self._client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema="keyword",
                )
            except Exception as e:
                logger.debug("create_payload_index(%s): %s", field_name, e)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        from qdrant_client.models import PointStruct

        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must be same length")
        points = [
            PointStruct(
                id=c.point_id(),
                vector=v,
                payload={"id": c.id, "text": c.text, **c.metadata},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        self._client.upsert(collection_name=self.collection, points=points)

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        qfilter = None
        if filters:
            must = []
            for k, v in filters.items():
                if isinstance(v, list):
                    must.append(FieldCondition(key=k, match=MatchAny(any=v)))
                else:
                    must.append(FieldCondition(key=k, match=MatchValue(value=v)))
            qfilter = Filter(must=must)

        # qdrant-client ≥1.10 dropped `.search` in favor of `.query_points`.
        results = self._client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=limit,
            query_filter=qfilter,
            with_payload=True,
        ).points

        out: list[SearchHit] = []
        for r in results:
            payload = dict(r.payload or {})
            chunk_id = payload.pop("id", str(r.id))
            text = payload.pop("text", "")
            out.append(SearchHit(id=chunk_id, score=float(r.score), text=text, metadata=payload))
        return out

    def count(self) -> int:
        return int(self._client.count(self.collection, exact=True).count)

    def delete_collection(self) -> None:
        try:
            self._client.delete_collection(self.collection)
        except Exception as e:
            logger.debug("delete_collection failed: %s", e)

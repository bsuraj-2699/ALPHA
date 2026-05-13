"""Embedding adapters.

Two backends are available:
    * `FastEmbedEmbedder` (default) — local BGE models via fastembed. No API
      key required; the model downloads once and is cached on disk. Default
      checkpoint is BAAI/bge-small-en-v1.5 (384-dim, ~30MB) so tests don't
      have to pull a multi-GB blob.
    * `OpenAIEmbedder` — text-embedding-3-large (3072-dim). Requires
      OPENAI_API_KEY.

Pick the backend with `EMBEDDING_PROVIDER` (`fastembed` | `openai`) and
`EMBEDDING_MODEL`. Both implement the same async `.embed(texts)` interface.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local embeddings via the fastembed library (Qdrant)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self.name = "fastembed"
        self.model_name = model_name
        self._model = TextEmbedding(model_name)
        # The model description carries dim; fall back to first embedding if
        # the metadata isn't populated.
        self.dim = self._infer_dim()

    def _infer_dim(self) -> int:
        try:
            for desc in TextEmbedding.list_supported_models():
                if desc.get("model") == self.model_name:
                    return int(desc["dim"])
        except Exception:
            pass
        # Probe with a single token
        sample = list(self._model.embed(["x"]))
        return len(sample[0])

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


class OpenAIEmbedder:
    """text-embedding-3-large (or any OpenAI embedding model)."""

    def __init__(self, model: str = "text-embedding-3-large", api_key: str | None = None) -> None:
        from openai import OpenAI

        self.name = "openai"
        self.model = model
        self._client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        # text-embedding-3-large is 3072; -small is 1536.
        self.dim = 3072 if "3-large" in model else 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        # OpenAI accepts batches of up to ~2048 inputs; chunk to be safe.
        out: list[list[float]] = []
        batch_size = 256
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]
            resp = self._client.embeddings.create(model=self.model, input=chunk)
            out.extend(d.embedding for d in resp.data)
        return out


def get_default_embedder() -> Embedder:
    provider = os.getenv("EMBEDDING_PROVIDER", "fastembed").lower()
    model = os.getenv("EMBEDDING_MODEL")
    if provider == "openai":
        return OpenAIEmbedder(model or "text-embedding-3-large")
    return FastEmbedEmbedder(model or "BAAI/bge-small-en-v1.5")


__all__: list[str] = [
    "Embedder",
    "FastEmbedEmbedder",
    "OpenAIEmbedder",
    "get_default_embedder",
]
# Avoid unused import warning when the protocol is the only thing
# imported from this module.
_ = Any

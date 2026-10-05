import asyncio
import hashlib
import math
from abc import ABC, abstractmethod
from functools import lru_cache

from app.config import settings
from app.memory.fake import _tokens


class EmbeddingProvider(ABC):
    """Text to vector. Separate from the chat LLM on purpose: embeddings come from a local model."""

    model_name: str
    dims: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in order. Batch calls are cheaper than many single calls."""


class FakeEmbedder(EmbeddingProvider):
    """Offline and deterministic: hashed bag of words, L2-normalised. Shared words mean higher cosine. Not semantic."""

    def __init__(self, dims: int = 384) -> None:
        self.dims, self.model_name = dims, f"fake-hash-{dims}"
        self.calls = 0
        self.fail = False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("fake embedding failure")
        out = []
        for t in texts:
            v = [0.0] * self.dims
            for tok in _tokens(t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dims] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class FastEmbedEmbedder(EmbeddingProvider):
    def __init__(self, model: str, dims: int) -> None:
        from fastembed import TextEmbedding  # optional dependency: requirements-embeddings.txt

        self.model_name, self.dims = model, dims
        self._model = TextEmbedding(model_name=model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(lambda: [[float(x) for x in v] for v in self._model.embed(texts)])


class CachedEmbedder(EmbeddingProvider):
    """Small in-process cache: the same text (a repeated query, a retried write) is never embedded twice."""

    def __init__(self, inner: EmbeddingProvider, max_size: int = 512) -> None:
        self.inner, self.max_size = inner, max_size
        self.model_name, self.dims = inner.model_name, inner.dims
        self._cache: dict[str, list[float]] = {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(t for t in texts if t not in self._cache))
        if missing:
            for t, v in zip(missing, await self.inner.embed(missing), strict=True):
                if len(self._cache) >= self.max_size:
                    self._cache.pop(next(iter(self._cache)))  # drop the oldest
                self._cache[t] = v
        return [self._cache[t] for t in texts]


@lru_cache
def get_embedder() -> EmbeddingProvider:
    if settings.embedding_provider == "fastembed":
        return CachedEmbedder(FastEmbedEmbedder(settings.embedding_model, settings.embedding_dims))
    return CachedEmbedder(FakeEmbedder(settings.embedding_dims))

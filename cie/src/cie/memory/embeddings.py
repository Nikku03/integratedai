"""Embedding providers. All return L2-normalised float vectors of ``dim``."""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from cie.core.settings import Settings, get_settings


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashedEmbedding:
    """Deterministic feature-hashing embedding (unigrams + bigrams, signed).

    No model download, no network. It is a *lexical* embedding and is used in
    tests and as a fallback; it is not expected to match a neural model on
    semantic queries. The benchmark reports which provider produced its numbers.
    """

    name = "hashed"

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            toks = re.findall(r"[a-z0-9]+", t.lower())
            feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:], strict=False)]
            for f in feats:
                h = int(hashlib.blake2b(f.encode(), digest_size=8).hexdigest(), 16)
                idx = h % self.dim
                sign = 1.0 if (h >> 63) & 1 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class FastEmbedProvider:
    name = "fastembed"

    def __init__(self, model: str, cache_dir: str, dim: int):
        from fastembed import TextEmbedding

        self.model_name = model
        self.dim = dim
        self._model = TextEmbedding(model, cache_dir=cache_dir)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = list(self._model.embed(texts, batch_size=32))
        out = []
        for v in vecs:
            arr = v.tolist()
            if len(arr) != self.dim:
                raise ValueError(f"embedding dim {len(arr)} != configured {self.dim}")
            out.append(arr)
        return out


class SentenceTransformersProvider:
    """PyTorch sentence-transformers model, on CUDA when available (Colab GPU path).
    Same model family as fastembed's default, so vectors are 384-d and normalised."""

    name = "sentence_transformers"

    def __init__(self, model: str, cache_dir: str, dim: int):
        import torch
        from sentence_transformers import SentenceTransformer

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model_name = model
        self.dim = dim
        self._model = SentenceTransformer(model, device=self.device, cache_folder=cache_dir)
        if self.device == "cuda":
            self._model.half()  # fp16 on the GPU: twice the throughput, normalised 384-d output unchanged to 3 decimals
        self.batch_size = 512 if self.device == "cuda" else 64
        self.name = f"sentence_transformers[{self.device}]"

    def embed(self, texts: list[str]) -> list[list[float]]:
        arr = self._model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        if arr.shape[1] != self.dim:
            raise ValueError(f"embedding dim {arr.shape[1]} != configured {self.dim}")
        return arr.tolist()


class OpenAIEmbedding:
    name = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 384):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dim)
        return [d.embedding for d in r.data]


@lru_cache(maxsize=4)
def _cached_provider(provider: str, model: str, cache_dir: str, dim: int, key: str) -> EmbeddingProvider:
    if provider == "fastembed":
        try:
            return FastEmbedProvider(model, cache_dir, dim)
        except Exception as e:  # model missing/offline -> explicit fallback with a warning
            import structlog

            structlog.get_logger(__name__).warning("fastembed unavailable, using hashed embeddings", error=str(e))
            return HashedEmbedding(dim)
    if provider == "sentence_transformers":
        return SentenceTransformersProvider(model, cache_dir, dim)
    if provider == "openai":
        return OpenAIEmbedding(key, model, dim)
    return HashedEmbedding(dim)


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    s = settings or get_settings()
    return _cached_provider(s.embedding_provider, s.embedding_model, str(s.model_cache), s.embedding_dim, s.openai_api_key)

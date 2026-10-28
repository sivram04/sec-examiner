"""Local CPU models via fastembed (ONNX): bge-small embeddings and a bge cross-encoder reranker.

HashEmbedder is a deterministic stand-in for tests, so CI never downloads models.
"""
import hashlib
import re
from typing import Protocol

import numpy as np

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "BAAI/bge-reranker-base"
# bge models retrieve better when queries carry this instruction
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    dim: int
    def embed_docs(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedder:
    dim = 384

    def __init__(self, model: str = EMBED_MODEL):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model)

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        return np.array(list(self.model.embed(texts, batch_size=64)), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.array(next(iter(self.model.embed([QUERY_PREFIX + text]))), dtype=np.float32)


class HashEmbedder:
    """Bag-of-hashed-words vectors: cheap, deterministic, lexically meaningful."""
    dim = 256

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model: str = RERANK_MODEL):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model)

    def score(self, query: str, texts: list[str]) -> list[float]:
        return list(self.model.rerank(query, texts, batch_size=16))

"""Tiny deterministic stand-ins for bge-m3 and bge-reranker (tests must not load 2 GB models)."""

from __future__ import annotations

import hashlib
import math

from kila.rag.bm25 import tokenize


class HashEmbedder:
    """Bag-of-words hashed into 256 dims, L2-normalised: similar words -> similar vectors."""

    name, device, dim = "fake-hash-embedder", "cpu", 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in tokenize(t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class OverlapReranker:
    """Relevance = fraction of query tokens present in the passage."""

    name, device, top_n = "fake-overlap-reranker", "cpu", 30

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(tokenize(query))
        return [len(q & set(tokenize(p))) / max(len(q), 1) for p in passages]

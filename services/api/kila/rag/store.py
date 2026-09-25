"""Qdrant vector store for chunk embeddings. Embedded (on-disk, in-process) or server mode.

Embedded mode holds a file lock on data/qdrant, so exactly one client per process; the API
runs a single worker, which is what we want anyway.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from kila.settings import get_settings

_NS = uuid.UUID("6f1c3d2e-8b7a-4c1d-9e2f-4b5a6c7d8e9f")
_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_NS, chunk_id))  # Qdrant ids must be UUIDs or ints


class VectorStore:
    def __init__(self, cfg: dict, dim: int):
        self.collection = cfg["collection"]
        if cfg.get("mode", "embedded") == "server":
            url = _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), cfg["url"])
            self.client = QdrantClient(url=url, timeout=30)
            self.where = url
        else:
            path = Path(cfg["path"])
            if not path.is_absolute():
                path = get_settings().data_dir / path.relative_to("data") if path.parts[0] == "data" else path
            path.mkdir(parents=True, exist_ok=True)
            self.client = QdrantClient(path=str(path))
            self.where = str(path)
        self.dim = dim
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(self.collection, vectors_config=qm.VectorParams(
                size=dim, distance=qm.Distance.COSINE))

    def upsert(self, chunk_ids: list[str], vectors: list[list[float]], payloads: list[dict]) -> None:
        points = [qm.PointStruct(id=point_id(cid), vector=v, payload={**p, "chunk_id": cid})
                  for cid, v, p in zip(chunk_ids, vectors, payloads)]
        for i in range(0, len(points), 128):
            self.client.upsert(self.collection, points=points[i:i + 128], wait=True)

    def delete_object(self, object_id: str) -> None:
        self.client.delete(self.collection, points_selector=qm.FilterSelector(filter=qm.Filter(
            must=[qm.FieldCondition(key="object_id", match=qm.MatchValue(value=object_id))])), wait=True)

    def search(self, vector: list[float], k: int, object_ids: list[str] | None = None) -> list[tuple[str, float]]:
        flt = None
        if object_ids:
            flt = qm.Filter(must=[qm.FieldCondition(key="object_id", match=qm.MatchAny(any=object_ids))])
        res = self.client.query_points(self.collection, query=vector, limit=k, query_filter=flt, with_payload=True)
        return [(p.payload["chunk_id"], float(p.score)) for p in res.points]

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def close(self) -> None:
        self.client.close()


_store: VectorStore | None = None
_lock = threading.Lock()


def get_store(cfg: dict, dim: int) -> VectorStore:
    global _store
    with _lock:
        if _store is None or _store.dim != dim:
            if _store is not None:
                _store.close()
            _store = VectorStore(cfg, dim)
        return _store


def reset_store() -> None:
    global _store
    with _lock:
        if _store is not None:
            _store.close()
        _store = None

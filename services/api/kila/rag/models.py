"""Embedder (bge-m3) and reranker (bge-reranker-v2-m3), loaded lazily from local paths only.

Tests swap in small deterministic fakes with `set_embedder` / `set_reranker`.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Protocol

from kila.settings import REPO_ROOT

log = logging.getLogger(__name__)


class ModelUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    name: str
    device: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    name: str
    device: str
    top_n: int

    def score(self, query: str, passages: list[str]) -> list[float]: ...  # 0..1, higher is better


def _device(pref: str) -> str:
    if pref != "auto":
        return pref
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _local_path(p: str) -> Path:
    path = Path(p) if Path(p).is_absolute() else REPO_ROOT / p
    if not (path / "config.json").exists():
        raise ModelUnavailable(f"model not found at {path}. Run scripts/predownload.py --only hf --yes while online.")
    return path


class BgeM3:
    def __init__(self, cfg: dict):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer

        path = _local_path(cfg["path"])
        self.device = _device(cfg.get("device", "auto"))
        t0 = time.perf_counter()
        self._m = SentenceTransformer(str(path), device=self.device, local_files_only=True)
        if self.device == "cuda":
            self._m.half()
        self._m.max_seq_length = cfg.get("max_seq_length", 1024)
        self.batch = cfg.get("batch_size", 16)
        get_dim = getattr(self._m, "get_embedding_dimension", None) or self._m.get_sentence_embedding_dimension
        self.dim = get_dim()
        self.name = path.name
        self.load_ms = round((time.perf_counter() - t0) * 1000)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs = self._m.encode(texts, batch_size=self.batch, normalize_embeddings=True, show_progress_bar=False)
        return vecs.tolist()


class BgeReranker:
    def __init__(self, cfg: dict):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import CrossEncoder

        path = _local_path(cfg["path"])
        self.device = _device(cfg.get("device", "auto"))
        on_gpu = self.device == "cuda"
        max_len = cfg.get("max_length", 512) if on_gpu else cfg.get("max_length_cpu", 320)
        self.top_n = cfg.get("top_n_gpu", 30) if on_gpu else cfg.get("top_n_cpu", 8)
        t0 = time.perf_counter()
        self._m = CrossEncoder(str(path), device=self.device, max_length=max_len, local_files_only=True)
        if on_gpu:
            self._m.model.half()
        self.name = path.name
        self.load_ms = round((time.perf_counter() - t0) * 1000)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        raw = self._m.predict([(query, p) for p in passages], batch_size=16, show_progress_bar=False,
                              activation_fn=None)
        return [1 / (1 + math.exp(-float(x))) for x in raw]  # logits -> 0..1 relevance


_lock = threading.Lock()
_embedder: Embedder | None = None
_reranker: Reranker | None = None


def get_embedder(cfg: dict) -> Embedder:
    global _embedder
    with _lock:
        if _embedder is None:
            _embedder = BgeM3(cfg)
            log.info("embedder %s on %s loaded in %s ms", _embedder.name, _embedder.device, _embedder.load_ms)
        return _embedder


def get_reranker(cfg: dict) -> Reranker:
    global _reranker
    with _lock:
        if _reranker is None:
            _reranker = BgeReranker(cfg)
            log.info("reranker %s on %s loaded in %s ms", _reranker.name, _reranker.device, _reranker.load_ms)
        return _reranker


def loaded() -> dict:
    return {
        "embedder": _embedder and {"name": _embedder.name, "device": _embedder.device},
        "reranker": _reranker and {"name": _reranker.name, "device": _reranker.device, "top_n": _reranker.top_n},
    }


def set_embedder(e: Embedder | None) -> None:
    global _embedder
    _embedder = e


def set_reranker(r: Reranker | None) -> None:
    global _reranker
    _reranker = r

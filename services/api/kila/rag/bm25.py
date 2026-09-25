"""BM25 over the SQLite chunk table, rebuilt in memory whenever the chunk set changes."""

from __future__ import annotations

import re
import threading

from rank_bm25 import BM25Okapi

# Keep engineering tokens whole: PV-101, 6"-P-1045-A1B, 0.425, H2S, bar(g).
_TOKEN = re.compile(r"[A-Za-z]+[0-9]*(?:-[A-Za-z0-9]+)+|\d+(?:\.\d+)?|\w+", re.UNICODE)
_STOP = frozenset("a an and are as at be by for from has have in is it of on or shall that the this to was were "
                  "will with which what when where who how".split())


def tokenize(text: str) -> list[str]:
    toks = [t.lower() for t in _TOKEN.findall(text)]
    out = [t for t in toks if t not in _STOP]
    # also index the parts of hyphenated tags so "N3" or "1045" alone still match
    for t in toks:
        if "-" in t:
            out.extend(p for p in t.split("-") if p and p not in _STOP)
    return out


class Bm25Index:
    def __init__(self):
        self._lock = threading.Lock()
        self._version: object = None
        self._ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    def ensure(self, version: object, rows: "callable") -> None:
        """Rebuild if `version` changed. `rows()` returns [(chunk_id, text)]."""
        with self._lock:
            if version == self._version and self._bm25 is not None:
                return
            data = rows()
            self._ids = [cid for cid, _ in data]
            corpus = [tokenize(text) for _, text in data]
            self._bm25 = BM25Okapi(corpus) if corpus else None
            self._version = version

    def search(self, query: str, k: int) -> list[tuple[str, float]]:
        with self._lock:
            if self._bm25 is None:
                return []
            q = tokenize(query)
            if not q:
                return []
            scores = self._bm25.get_scores(q)
            order = scores.argsort()[::-1][:k]
            return [(self._ids[i], float(scores[i])) for i in order if scores[i] > 0]

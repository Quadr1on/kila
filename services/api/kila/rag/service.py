"""Indexing and hybrid search (spec §6.5).

index:  ingestion result -> page-bounded chunks (SQLite, for citations + BM25) -> bge-m3 -> Qdrant
search: dense top-k + BM25 top-k -> Reciprocal Rank Fusion -> cross-encoder rerank -> top final_k
Every stage is returned with timings so the playground can show *why* a passage ranked.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, delete, func, select

from kila import ledger
from kila.db.models import Bucket, Ingestion, KBChunk, KBDocument, StoredObject, utcnow
from kila.db.session import get_engine
from kila.ingest import service as ingest
from kila.rag import models as rag_models
from kila.rag.bm25 import Bm25Index
from kila.rag.chunking import chunk_page
from kila.rag.store import get_store
from kila.settings import get_settings

log = logging.getLogger(__name__)
_bm25 = Bm25Index()
_generation = 0  # bumped whenever the chunk set changes; BM25 rebuilds lazily
_gen_lock = threading.Lock()


@lru_cache
def _load_cfg(path: Path, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def config() -> dict[str, Any]:
    p = get_settings().config_dir / "rag.yaml"
    return _load_cfg(p, p.stat().st_mtime)


def _bump() -> None:
    global _generation
    with _gen_lock:
        _generation += 1


def embedder():
    return rag_models.get_embedder(config()["embedder"])


def reranker():
    return rag_models.get_reranker(config()["reranker"])


def vector_store():
    return get_store(config()["qdrant"], embedder().dim)


# ------------------------------------------------------------------ indexing

def _doc_type(name: str, kind: str) -> str:
    up = name.upper()
    for prefix, t in (("SOP-", "procedure"), ("STD-", "standard"), ("GUIDE-", "guide"), ("IR-", "inspection_report")):
        if up.startswith(prefix):
            return t
    return {"sheet": "spreadsheet", "code": "code"}.get(kind, "document")


def _title(att) -> str:
    for p in att.pages[:1]:
        for line in p.text.splitlines()[:6]:
            s = line.strip()
            if len(s) > 12 and not s.lower().startswith(("konkan", "page ")):
                return s[:140]
    return att.name


def request_index(object_id: str, *, actor: str, user_id: int | None = None, lang: str = "en") -> KBDocument:
    """Mark an object for indexing. Runs after (or immediately if) its ingestion is done."""
    with Session(get_engine()) as s:
        obj = s.get(StoredObject, object_id)
        doc = s.exec(select(KBDocument).where(KBDocument.object_id == object_id)).first()
        if doc is None:
            doc = KBDocument(object_id=object_id, title=obj.original_name, doc_type=_doc_type(obj.original_name, ""))
        doc.status, doc.error = "pending", None
        s.add(doc)
        s.commit()
        s.refresh(doc)
    ing_row = ingest.submit(object_id, lang=lang, user_id=user_id, actor=actor)
    if ing_row.status == "done":  # cached or already extracted: index on the worker now
        ingest.pool().submit(_index_safely, object_id, actor)
    return doc


def _on_ingestion_done(ingestion_id: str) -> None:
    """Ingestion listener: index objects that were waiting for their extraction."""
    with Session(get_engine()) as s:
        ing = s.get(Ingestion, ingestion_id)
        if ing is None:
            return
        doc = s.exec(select(KBDocument).where(KBDocument.object_id == ing.object_id)).first()
        if doc is None or doc.status not in ("pending", "indexing"):
            return
        if ing.status == "error":
            doc.status, doc.error = "error", f"extraction failed: {ing.error}"
            s.add(doc)
            s.commit()
            return
        object_id = ing.object_id
    _index_safely(object_id, "system")


ingest.on_done(_on_ingestion_done)


def _index_safely(object_id: str, actor: str) -> None:
    try:
        index_object(object_id, actor)
    except Exception as e:
        log.exception("indexing %s failed", object_id)
        with Session(get_engine()) as s:
            doc = s.exec(select(KBDocument).where(KBDocument.object_id == object_id)).first()
            if doc:
                doc.status, doc.error = "error", f"{type(e).__name__}: {e}"[:500]
                s.add(doc)
                s.commit()
        ledger.append(actor, "kb.index_failed", {"object_id": object_id, "error": f"{type(e).__name__}: {e}"[:300]})


def index_object(object_id: str, actor: str = "system") -> dict[str, Any]:
    cfg = config()
    with Session(get_engine()) as s:
        ing = ingest.latest(s, object_id)
        att = ingest.attachment_of(ing) if ing else None
        if att is None:
            raise RuntimeError("object has no finished extraction")
        obj = s.get(StoredObject, object_id)
        bucket = s.get(Bucket, obj.bucket_id).name
        doc = s.exec(select(KBDocument).where(KBDocument.object_id == object_id)).first()
        if doc is None:
            doc = KBDocument(object_id=object_id, title=att.name, doc_type="document")
        doc.status, doc.title, doc.doc_type = "indexing", _title(att), _doc_type(att.name, att.kind)
        s.add(doc)
        s.commit()
        s.refresh(doc)
        doc_id = doc.id

    ck = cfg["chunking"]
    chunks = [c for p in att.pages for c in chunk_page(p.text, p.index, ck["target_tokens"], ck["overlap_tokens"],
                                                           ck["min_chunk_chars"])]
    rows = [KBChunk(id=f"{object_id}:p{c.page}:{c.index}", kb_document_id=doc_id, object_id=object_id,
                    page=c.page, char_start=c.char_start, char_end=c.char_end, text=c.text) for c in chunks]

    t0 = time.perf_counter()
    emb = embedder()
    # Prefix the heading/title so a chunk's topic survives even when the passage itself is terse.
    vectors = emb.embed([f"{doc.title}\n{c.heading or ''}\n{c.text}".strip() for c in chunks]) if chunks else []
    embed_ms = round((time.perf_counter() - t0) * 1000, 1)

    store = vector_store()
    store.delete_object(object_id)
    store.upsert([r.id for r in rows], vectors, [{"object_id": object_id, "page": r.page, "bucket": bucket,
                                                   "doc_id": doc_id} for r in rows])
    with Session(get_engine()) as s:
        s.exec(delete(KBChunk).where(KBChunk.object_id == object_id))
        for r in rows:
            s.add(r)
        doc = s.get(KBDocument, doc_id)
        doc.status, doc.error, doc.chunk_count, doc.indexed_at = "indexed", None, len(rows), utcnow()
        s.add(doc)
        s.commit()
    _bump()
    result = {"object_id": object_id, "sha256": att.sha256, "bucket": bucket, "chunks": len(rows),
              "pages": len(att.pages), "embed_ms": embed_ms, "embedder": emb.name, "device": emb.device,
              "chunks_per_s": round(len(rows) / (embed_ms / 1000), 2) if embed_ms and rows else None}
    ledger.append(actor, "kb.indexed", result)
    _record_metric("index", result)
    return result


def remove(object_id: str, actor: str) -> None:
    vector_store().delete_object(object_id)
    with Session(get_engine()) as s:
        s.exec(delete(KBChunk).where(KBChunk.object_id == object_id))
        s.exec(delete(KBDocument).where(KBDocument.object_id == object_id))
        s.commit()
    _bump()
    ledger.append(actor, "kb.removed", {"object_id": object_id})


# ------------------------------------------------------------------ search

def _bm25_rows() -> list[tuple[str, str]]:
    with Session(get_engine()) as s:
        return [(c.id, c.text) for c in s.exec(select(KBChunk)).all()]


def _chunk_count() -> int:
    with Session(get_engine()) as s:
        return s.exec(select(func.count()).select_from(KBChunk)).one()


def rrf(rankings: list[list[str]], k: int) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _hydrate(ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    with Session(get_engine()) as s:
        rows = s.exec(select(KBChunk, StoredObject, KBDocument, Bucket)
                      .join(StoredObject, StoredObject.id == KBChunk.object_id)
                      .join(KBDocument, KBDocument.id == KBChunk.kb_document_id)
                      .join(Bucket, Bucket.id == StoredObject.bucket_id)
                      .where(KBChunk.id.in_(ids), StoredObject.deleted_at.is_(None))).all()
    return {c.id: {"chunk_id": c.id, "object_id": c.object_id, "name": o.original_name, "title": d.title,
                   "doc_type": d.doc_type, "bucket": b.name, "page": c.page, "char_start": c.char_start,
                   "char_end": c.char_end, "text": c.text} for c, o, d, b in rows}


def search(query: str, *, object_ids: list[str] | None = None, buckets: tuple[str, ...] = ("kb",),
           final_k: int | None = None, rerank: bool = True) -> dict[str, Any]:
    """Hybrid search. `object_ids` restricts to those documents (e.g. the user's attachments);
    otherwise results come from `buckets` (the knowledge base by default)."""
    cfg = config()
    r = cfg["retrieval"]
    final_k = final_k or r["final_k"]
    timings: dict[str, float] = {}
    allowed_objects = set(object_ids) if object_ids else None

    t = time.perf_counter()
    qvec = embedder().embed([query])[0]
    timings["embed_query_ms"] = _ms(t)

    t = time.perf_counter()
    dense = vector_store().search(qvec, r["dense_k"] * (3 if allowed_objects is None else 1), object_ids)
    timings["dense_ms"] = _ms(t)

    t = time.perf_counter()
    _bm25.ensure((_generation, _chunk_count()), _bm25_rows)
    bm = _bm25.search(query, r["bm25_k"] * 4)
    timings["bm25_ms"] = _ms(t)

    meta = _hydrate(list({cid for cid, _ in dense} | {cid for cid, _ in bm}))

    def keep(cid: str) -> bool:
        m = meta.get(cid)
        if m is None:
            return False  # deleted object or stale vector
        return m["object_id"] in allowed_objects if allowed_objects is not None else m["bucket"] in buckets

    dense = [(c, s) for c, s in dense if keep(c)][: r["dense_k"]]
    bm = [(c, s) for c, s in bm if keep(c)][: r["bm25_k"]]
    fused = rrf([[c for c, _ in dense], [c for c, _ in bm]], r["rrf_k"])

    reranked: list[tuple[str, float]] = []
    rr_info: dict[str, Any] = {"enabled": rerank}
    if rerank and fused:
        rr = reranker()
        top = fused[: rr.top_n]
        t = time.perf_counter()
        scores = rr.score(query, [meta[c]["text"] for c, _ in top])
        timings["rerank_ms"] = _ms(t)
        reranked = sorted(zip([c for c, _ in top], scores), key=lambda kv: kv[1], reverse=True)
        rr_info.update({"model": rr.name, "device": rr.device, "top_n": rr.top_n, "candidates": len(top)})
    final = (reranked or fused)[:final_k]

    def rows(pairs):
        return [{**meta[c], "score": round(s, 4), "rank": i + 1} for i, (c, s) in enumerate(pairs)]

    out = {
        "query": query,
        "dense": rows(dense),
        "bm25": rows(bm),
        "fused": rows(fused[: max(final_k, 20)]),
        "reranked": rows(reranked),
        "results": rows(final),
        # 0..1 signal for the Phase 3 cascade router: best cross-encoder relevance
        "retrieval_relevance": round(reranked[0][1], 4) if reranked else None,
        "rerank": rr_info,
        "embedder": {"name": embedder().name, "device": embedder().device},
        "timings_ms": {**timings, "total_ms": round(sum(timings.values()), 1)},
    }
    _record_metric("search", {"timings_ms": out["timings_ms"], "rerank": rr_info, "n_results": len(final)})
    return out


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 1)


# ------------------------------------------------------------------ status / metrics

def documents(bucket: str = "kb") -> list[dict[str, Any]]:
    with Session(get_engine()) as s:
        rows = s.exec(select(KBDocument, StoredObject, Bucket)
                      .join(StoredObject, StoredObject.id == KBDocument.object_id)
                      .join(Bucket, Bucket.id == StoredObject.bucket_id)
                      .where(Bucket.name == bucket, StoredObject.deleted_at.is_(None))
                      .order_by(KBDocument.id.desc())).all()
        out = []
        for d, o, _ in rows:
            ing = ingest.latest(s, o.id)
            out.append({"object_id": o.id, "name": o.original_name, "sha256": o.sha256, "size": o.size,
                        "title": d.title, "doc_type": d.doc_type, "status": d.status, "error": d.error,
                        "chunk_count": d.chunk_count, "indexed_at": d.indexed_at,
                        "ingestion": ingest.summary(ing) if ing and ing.status != "done" else
                        ing and {"status": ing.status, "pages_total": ing.pages_total, "duration_ms": ing.duration_ms}})
        return out


def _record_metric(kind: str, row: dict[str, Any], keep: int = 1000) -> None:
    import json

    d = get_settings().metrics_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"rag_{kind}.json"
    try:
        runs = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except ValueError:
        runs = []
    runs.append({"ts": utcnow().isoformat(timespec="seconds"), **row})
    p.write_text(json.dumps(runs[-keep:], indent=1, default=str), encoding="utf-8")


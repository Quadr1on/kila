"""Ingestion jobs: run extraction in a background worker, cache by content hash, log to the ledger.

OCR is CPU-heavy, so one worker thread processes jobs in order. Jobs interrupted by an API
restart are re-queued on startup.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sqlmodel import Session, select

from kila import ledger
from kila.db.models import Ingestion, StoredObject, utcnow
from kila.db.session import get_engine
from kila.ingest.envelope import Attachment, TaskEnvelope, detect_language
from kila.ingest.extract import Extractor, encode_png
from kila.settings import get_settings
from kila.storage import store

log = logging.getLogger(__name__)
PIPELINE = "ingest-v2"  # bump when extraction output changes, to invalidate the cache

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()
_listeners: list = []  # callbacks(ingestion_id) run after a job finishes (the KB indexer uses this)


@lru_cache
def _load_cfg(path: Path, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def config() -> dict[str, Any]:
    p = get_settings().config_dir / "ingest.yaml"
    return _load_cfg(p, p.stat().st_mtime)


def pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")
        return _pool


def shutdown() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.shutdown(wait=True, cancel_futures=True)
            _pool = None


def on_done(callback) -> None:
    if callback not in _listeners:
        _listeners.append(callback)


# ------------------------------------------------------------ queries

def latest(session: Session, object_id: str) -> Ingestion | None:
    return session.exec(select(Ingestion).where(Ingestion.object_id == object_id)
                        .order_by(Ingestion.created_at.desc())).first()


def attachment_of(ing: Ingestion) -> Attachment | None:
    if ing.status != "done":
        return None
    return Attachment.model_validate_json(ing.attachment_json)


def _cached(session: Session, sha256: str, lang: str) -> Ingestion | None:
    return session.exec(select(Ingestion).where(Ingestion.sha256 == sha256, Ingestion.pipeline == PIPELINE,
                                                Ingestion.lang == lang, Ingestion.status == "done")
                        .order_by(Ingestion.finished_at.desc())).first()


# ------------------------------------------------------------ submit

def submit(object_id: str, *, lang: str = "en", user_id: int | None = None, actor: str = "system",
           force: bool = False) -> Ingestion:
    """Queue an extraction. Reuses an earlier result for identical content unless force=True."""
    with Session(get_engine()) as s:
        obj = store.get_object(s, object_id)
        sha = obj.sha256
        current = latest(s, object_id)
        if current and current.status in ("queued", "running") and not force:
            return current
        ing = Ingestion(object_id=object_id, sha256=obj.sha256, pipeline=PIPELINE, lang=lang, requested_by=user_id)
        hit = None if force else _cached(s, obj.sha256, lang)
        hit_id = hit.id if hit is not None else None
        if hit is not None:
            att = Attachment.model_validate_json(hit.attachment_json)
            att.object_id, att.name = obj.id, obj.original_name  # same bytes, different upload
            ing.status, ing.attachment_json = "done", att.model_dump_json()
            ing.pages_done = ing.pages_total = hit.pages_total
            ing.started_at = ing.finished_at = utcnow()
            ing.duration_ms = 0.0
        s.add(ing)
        s.commit()
        s.refresh(ing)
    if hit is not None:
        ledger.append(actor, "ingest.cache_hit", {"object_id": object_id, "sha256": sha,
                                                  "reused_ingestion": hit_id, "pipeline": PIPELINE})
        _notify(ing.id)
    else:
        ledger.append(actor, "ingest.queued", {"object_id": object_id, "sha256": sha, "lang": lang,
                                               "pipeline": PIPELINE, "ingestion_id": ing.id})
        pool().submit(_run_safely, ing.id, actor)
    return ing


def requeue_interrupted() -> int:
    """Called on startup: jobs that were queued/running when the API stopped get run again."""
    with Session(get_engine()) as s:
        stale = s.exec(select(Ingestion).where(Ingestion.status.in_(("queued", "running")))).all()
        ids = [i.id for i in stale]
        for i in stale:
            i.status, i.pages_done = "queued", 0
            s.add(i)
        s.commit()
    for iid in ids:
        pool().submit(_run_safely, iid, "system")
    return len(ids)


def wait_idle(timeout: float = 120) -> None:
    """Tests/CLI: block until every job submitted so far has finished."""
    f: Future = pool().submit(lambda: None)
    f.result(timeout=timeout)


# ------------------------------------------------------------ run

def _run_safely(ingestion_id: str, actor: str) -> None:
    try:
        _run(ingestion_id, actor)
    except Exception as e:  # never kill the worker thread
        log.exception("ingestion %s failed", ingestion_id)
        with Session(get_engine()) as s:
            ing = s.get(Ingestion, ingestion_id)
            if ing:
                ing.status, ing.error, ing.finished_at = "error", f"{type(e).__name__}: {e}"[:1000], utcnow()
                s.add(ing)
                s.commit()
                ledger.append(actor, "ingest.failed", {"object_id": ing.object_id, "sha256": ing.sha256,
                                                       "error": ing.error[:300]})
    _notify(ingestion_id)


def _run(ingestion_id: str, actor: str) -> None:
    with Session(get_engine()) as s:
        ing = s.get(Ingestion, ingestion_id)
        if ing is None or ing.status == "done":
            return
        obj = s.get(StoredObject, ing.object_id)
        bucket = store.bucket_name_of(s, obj)
        ing.status, ing.started_at, ing.error = "running", utcnow(), None
        s.add(ing)
        s.commit()
        meta = dict(object_id=obj.id, sha256=obj.sha256, name=obj.original_name, mime=obj.mime, lang=ing.lang)
    path = store.blob_path(bucket, meta["sha256"])

    def store_image(img: np.ndarray, label: str) -> tuple[str, tuple[int, int]]:
        with Session(get_engine()) as s2:
            o = store.put_object(s2, "thumbnails", io.BytesIO(encode_png(img)), f"{meta['object_id']}_{label}.png",
                                 user=None, path=f"pages/{meta['object_id']}/{label}.png", system=True,
                                 make_thumbnail=False, metadata={"page_of": meta["object_id"], "ingestion": ingestion_id})
            return o.id, (int(img.shape[1]), int(img.shape[0]))

    def progress(done: int, total: int) -> None:
        with Session(get_engine()) as s3:
            row = s3.get(Ingestion, ingestion_id)
            row.pages_done, row.pages_total = done, total
            s3.add(row)
            s3.commit()

    att = Extractor(config(), store_image, progress).run(path, **meta)
    with Session(get_engine()) as s:
        ing = s.get(Ingestion, ingestion_id)
        ing.status, ing.finished_at = "done", utcnow()
        ing.duration_ms = att.timings_ms.get("total")
        ing.attachment_json = att.model_dump_json()
        ing.pages_total = ing.pages_total or len(att.pages)
        ing.pages_done = ing.pages_total
        s.add(ing)
        s.commit()
    ocr_pages = [p for p in att.pages if p.method in ("ocr", "ocr+vision")]
    ledger.append(actor, "ingest.done", {
        "object_id": att.object_id, "sha256": att.sha256, "kind": att.kind, "pages": len(att.pages),
        "ocr_pages": len(ocr_pages), "vision_pages": sum(1 for p in att.pages if p.vision is not None),
        "mean_ocr_conf": round(sum(p.ocr_conf or 0 for p in ocr_pages) / len(ocr_pages), 4) if ocr_pages else None,
        "warnings": len(att.warnings), "duration_ms": att.timings_ms.get("total"), "pipeline": PIPELINE,
    })


def _notify(ingestion_id: str) -> None:
    for cb in list(_listeners):
        try:
            cb(ingestion_id)
        except Exception:
            log.exception("ingest listener failed")


# ------------------------------------------------------------ envelope

def build_envelope(envelope_id: str, user_text: str, object_ids: list[str]) -> TaskEnvelope:
    atts = []
    with Session(get_engine()) as s:
        for oid in object_ids:
            ing = latest(s, oid)
            att = attachment_of(ing) if ing else None
            if att:
                atts.append(att)
    return TaskEnvelope(id=envelope_id, user_text=user_text, language=detect_language(user_text), attachments=atts)


def summary(ing: Ingestion) -> dict[str, Any]:
    out = {"ingestion_id": ing.id, "object_id": ing.object_id, "status": ing.status, "lang": ing.lang,
           "pages_done": ing.pages_done, "pages_total": ing.pages_total, "error": ing.error,
           "pipeline": ing.pipeline, "duration_ms": ing.duration_ms,
           "created_at": ing.created_at, "finished_at": ing.finished_at}
    if ing.status == "done":
        out["attachment"] = json.loads(ing.attachment_json)
    return out

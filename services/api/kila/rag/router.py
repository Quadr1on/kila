from __future__ import annotations

import io
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from kila import ledger
from kila.auth.deps import current_user, require_role
from kila.db.models import User
from kila.db.session import get_session
from kila.rag import models as rag_models
from kila.rag import service
from kila.rag.models import ModelUnavailable
from kila.settings import REPO_ROOT
from kila.storage import store
from kila.storage.store import StorageError

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


@router.get("/documents")
def documents(_: User = Depends(current_user)) -> list[dict[str, Any]]:
    return service.documents("kb")


@router.get("/status")
def status(_: User = Depends(current_user)) -> dict[str, Any]:
    cfg = service.config()
    return {"models": rag_models.loaded(), "qdrant": {"mode": cfg["qdrant"]["mode"]},
            "retrieval": cfg["retrieval"], "rerank_top_n": {"gpu": cfg["reranker"]["top_n_gpu"],
                                                           "cpu": cfg["reranker"]["top_n_cpu"]}}


@router.post("/documents/{object_id}/index")
def index(object_id: str, lang: Literal["en", "hi", "kn", "auto"] = "en",
          user: User = Depends(require_role("engineer", "admin")),
          session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        obj = store.get_object(session, object_id)
        store.check_access(user, store.bucket_name_of(session, obj), "read")
    except StorageError as e:
        raise HTTPException(e.status, e.detail) from e
    doc = service.request_index(object_id, actor=user.name, user_id=user.id, lang=lang)
    return {"object_id": object_id, "status": doc.status}


@router.delete("/documents/{object_id}", status_code=204)
def remove(object_id: str, user: User = Depends(require_role("engineer", "admin")),
           session: Session = Depends(get_session)) -> None:
    try:
        store.soft_delete(session, object_id, user)
    except StorageError as e:
        raise HTTPException(e.status, e.detail) from e
    service.remove(object_id, user.name)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    object_ids: list[str] | None = None
    rerank: bool = True


@router.post("/search")
async def search(body: SearchIn, user: User = Depends(current_user)) -> dict[str, Any]:
    try:
        out = await run_in_threadpool(service.search, body.query, object_ids=body.object_ids, rerank=body.rerank)
    except ModelUnavailable as e:
        raise HTTPException(503, str(e)) from e
    import hashlib

    ledger.append(user.name, "kb.search", {
        "query_sha256": hashlib.sha256(body.query.encode()).hexdigest(),
        "results": [r["chunk_id"] for r in out["results"]],
        "retrieval_relevance": out["retrieval_relevance"], "total_ms": out["timings_ms"]["total_ms"],
    })
    return out


@router.post("/seed")
def load_demo_corpus(user: User = Depends(require_role("admin")),
                     session: Session = Depends(get_session)) -> dict[str, Any]:
    """Upload the SYNTHETIC seed corpus (seed/kb, seed/sheets, seed/reports) into the kb bucket and index it."""
    seed = REPO_ROOT / "seed"
    files = sorted((seed / "kb").glob("*.pdf")) + sorted((seed / "sheets").glob("*.xlsx")) + \
        sorted((seed / "reports").glob("*_scan.pdf"))
    if not files:
        raise HTTPException(404, "seed corpus not found; run scripts/make_seed_corpus.py")
    existing = {d["sha256"] for d in service.documents("kb")}
    queued = []
    for f in files:
        data = f.read_bytes()
        import hashlib

        if hashlib.sha256(data).hexdigest() in existing:
            continue
        obj = store.put_object(session, "kb", io.BytesIO(data), f.name, user=user, path=f"demo/{f.name}")
        service.request_index(obj.id, actor=user.name, user_id=user.id)
        queued.append(f.name)
    ledger.append(user.name, "kb.seed_loaded", {"files": queued})
    return {"queued": queued, "skipped": len(files) - len(queued)}

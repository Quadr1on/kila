from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from kila.auth.deps import current_user
from kila.db.models import User
from kila.db.session import get_session
from kila.ingest import service
from kila.storage import store
from kila.storage.store import StorageError

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _readable(session: Session, object_id: str, user: User) -> None:
    try:
        obj = store.get_object(session, object_id)
        store.check_access(user, store.bucket_name_of(session, obj), "read")
    except StorageError as e:
        raise HTTPException(e.status, e.detail) from e


@router.post("/{object_id}")
def start(
    object_id: str,
    lang: Literal["en", "hi", "kn", "auto"] = "en",
    force: bool = False,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Queue text extraction for a stored file. Returns immediately; poll GET for progress."""
    _readable(session, object_id, user)
    ing = service.submit(object_id, lang=lang, user_id=user.id, actor=user.name, force=force)
    return service.summary(ing)


@router.get("/{object_id}")
def status(
    object_id: str,
    include_lines: bool = Query(True, description="OCR boxes per page (for the confidence overlay)"),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _readable(session, object_id, user)
    ing = service.latest(session, object_id)
    if ing is None:
        return {"object_id": object_id, "status": "none"}
    out = service.summary(ing)
    if not include_lines and "attachment" in out:
        for p in out["attachment"]["pages"]:
            p["lines"] = []
    return out

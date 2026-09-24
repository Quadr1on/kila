from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from kila.auth.deps import current_user
from kila.db.models import Bucket, StoredObject, User
from kila.db.session import get_session
from kila.settings import get_settings
from kila.storage import signing, store
from kila.storage.store import StorageError

router = APIRouter(prefix="/storage", tags=["storage"])

# Only these render inline; everything else downloads (uploaded HTML/SVG must never
# execute in the app's origin).
_INLINE_SAFE = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff",
                "application/pdf", "text/plain", "text/csv")


class ObjectOut(BaseModel):
    object_id: str
    bucket: str
    path: str
    sha256: str
    size: int
    mime: str
    original_name: str
    uploaded_by: int | None
    created_at: datetime
    metadata: dict[str, Any]
    thumbnail_url: str | None = None


class SignedUrlOut(BaseModel):
    url: str
    expires_at: int


def _raise(e: StorageError) -> None:
    raise HTTPException(e.status, e.detail) from e


def _out(obj: StoredObject, bucket: str, *, with_thumb: bool = True) -> ObjectOut:
    meta = json.loads(obj.metadata_json or "{}")
    thumb_url = None
    if with_thumb and meta.get("thumbnail_object_id"):
        thumb_url, _ = signing.sign(meta["thumbnail_object_id"],
                                    get_settings().app["storage"]["signed_url_default_ttl_s"])
    return ObjectOut(object_id=obj.id, bucket=bucket, path=obj.path, sha256=obj.sha256, size=obj.size,
                     mime=obj.mime, original_name=obj.original_name, uploaded_by=obj.uploaded_by,
                     created_at=obj.created_at, metadata=meta, thumbnail_url=thumb_url)


def _file_response(obj: StoredObject, path) -> FileResponse:  # noqa: ANN001
    inline = obj.mime in _INLINE_SAFE
    return FileResponse(
        path, media_type=obj.mime if inline else "application/octet-stream",
        filename=obj.original_name, content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=60"},
    )


@router.get("/buckets")
def buckets(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    return [
        {"name": b.name, "can_read": store.can(user, b.name, "read"), "can_write": store.can(user, b.name, "write")}
        for b in session.exec(select(Bucket).order_by(Bucket.name)).all()
    ]


# Object routes are declared before /{bucket}/... so "object" / "signed" never parse as bucket names.

@router.get("/object/{object_id}")
def download(object_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    try:
        obj = store.get_object(session, object_id)
        store.check_access(user, store.bucket_name_of(session, obj), "read")
        obj, path = store.open_for_read(session, object_id, actor=user.name, via="api")
    except StorageError as e:
        _raise(e)
    return _file_response(obj, path)


@router.get("/object/{object_id}/meta", response_model=ObjectOut)
def meta(object_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)):
    try:
        obj = store.get_object(session, object_id)
        bucket = store.bucket_name_of(session, obj)
        store.check_access(user, bucket, "read")
    except StorageError as e:
        _raise(e)
    return _out(obj, bucket)


@router.post("/object/{object_id}/signed-url", response_model=SignedUrlOut)
def signed_url(
    object_id: str,
    expires: int = Query(default=None, ge=1),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    cfg = get_settings().app["storage"]
    ttl = min(expires or cfg["signed_url_default_ttl_s"], cfg["signed_url_max_ttl_s"])
    try:
        obj = store.get_object(session, object_id)
        store.check_access(user, store.bucket_name_of(session, obj), "read")
    except StorageError as e:
        _raise(e)
    url, exp = signing.sign(object_id, ttl)
    return SignedUrlOut(url=url, expires_at=exp)


@router.get("/signed/{object_id}")
def signed_download(object_id: str, exp: int, sig: str, session: Session = Depends(get_session)):
    if not signing.check(object_id, exp, sig):
        raise HTTPException(403, "invalid or expired signature")
    try:
        obj, path = store.open_for_read(session, object_id, actor="signed-url", via="signed_url")
    except StorageError as e:
        _raise(e)
    return _file_response(obj, path)


@router.delete("/object/{object_id}", status_code=204)
def delete(object_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)) -> None:
    try:
        store.soft_delete(session, object_id, user)
    except StorageError as e:
        _raise(e)


@router.post("/{bucket}/upload", response_model=ObjectOut)
def upload(
    bucket: str,
    file: UploadFile = File(...),
    path: str | None = Form(default=None),
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        obj = store.put_object(session, bucket, file.file, file.filename or "file", user=user, path=path)
    except StorageError as e:
        _raise(e)
    return _out(obj, bucket)


@router.get("/{bucket}/list", response_model=list[ObjectOut])
def list_bucket(
    bucket: str,
    prefix: str = "",
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
):
    try:
        store.check_access(user, bucket, "read")
        objs = store.list_objects(session, bucket, prefix)
    except StorageError as e:
        _raise(e)
    return [_out(o, bucket) for o in objs]

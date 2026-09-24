"""KILA Local Bucket: content-addressed blobs on disk + metadata rows in `objects`.

Layout: data/buckets/<bucket>/objects/<sha[0:2]>/<sha[2:4]>/<sha256>
Identical content in the same bucket is stored once; every upload still gets its own
`objects` row (who uploaded what, when). Deletes are soft: rows are flagged, blobs stay.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

import filetype
from sqlmodel import Session, select

from kila import ledger
from kila.db.models import Bucket, StoredObject, User, utcnow
from kila.settings import get_settings

log = logging.getLogger(__name__)
CHUNK = 1024 * 1024

# Office formats are ZIP containers; magic-byte sniffing only sees "zip".
_ZIP_BASED = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
_TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".md", ".csv", ".json", ".yaml", ".yml", ".txt", ".toml", ".sql", ".c", ".cpp", ".h", ".java", ".go", ".rs"}


class StorageError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ---------------------------------------------------------------- blobs

def blob_path(bucket: str, sha256: str) -> Path:
    return get_settings().buckets_dir / bucket / "objects" / sha256[:2] / sha256[2:4] / sha256


def write_blob(bucket: str, data: BinaryIO, max_bytes: int) -> tuple[str, int, bytes]:
    """Stream to a temp file while hashing, then move into place. Returns (sha, size, head)."""
    tmp_dir = get_settings().buckets_dir / bucket / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    size = 0
    head = b""
    fd, tmp_name = tempfile.mkstemp(dir=tmp_dir)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := data.read(CHUNK):
                if not head:
                    head = chunk[:8192]
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError(413, f"file exceeds {max_bytes // (1024 * 1024)} MB limit")
                h.update(chunk)
                out.write(chunk)
        sha = h.hexdigest()
        dest = blob_path(bucket, sha)
        if dest.exists():
            os.unlink(tmp_name)  # dedup: identical content already stored
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_name, dest)
        return sha, size, head
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def detect_mime(head: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    kind = filetype.guess(head) if head else None
    if kind is not None:
        if kind.mime == "application/zip" and ext in _ZIP_BASED:
            return _ZIP_BASED[ext]
        return kind.mime
    if ext in _ZIP_BASED:
        return _ZIP_BASED[ext]
    if ext in _TEXT_EXT:
        return "text/csv" if ext == ".csv" else "text/plain"
    guessed, _ = mimetypes.guess_type(filename)
    if guessed:
        return guessed
    try:
        head.decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "application/octet-stream"


# ---------------------------------------------------------------- access

def get_bucket(session: Session, name: str) -> Bucket:
    b = session.exec(select(Bucket).where(Bucket.name == name)).first()
    if b is None:
        raise StorageError(404, f"bucket '{name}' not found")
    return b


def can(user: User, bucket_name: str, op: str) -> bool:
    rules = get_settings().app["storage"]["buckets"].get(bucket_name)
    return bool(rules) and user.role in rules.get(op, [])


def check_access(user: User, bucket_name: str, op: str) -> None:
    if not can(user, bucket_name, op):
        raise StorageError(403, f"role '{user.role}' cannot {op} bucket '{bucket_name}'")


def bucket_name_of(session: Session, obj: StoredObject) -> str:
    b = session.get(Bucket, obj.bucket_id)
    assert b is not None
    return b.name


# ---------------------------------------------------------------- objects

def put_object(
    session: Session,
    bucket_name: str,
    data: BinaryIO,
    original_name: str,
    *,
    user: User | None,
    path: str | None = None,
    metadata: dict[str, Any] | None = None,
    system: bool = False,
    make_thumbnail: bool = True,
) -> StoredObject:
    """Store a file. `system=True` skips role checks (internal writers like the renderer)."""
    if not system:
        if user is None:
            raise StorageError(401, "not authenticated")
        check_access(user, bucket_name, "write")
    bucket = get_bucket(session, bucket_name)
    cfg = get_settings().app["storage"]
    original_name = Path(original_name or "file").name[:255]
    sha, size, head = write_blob(bucket_name, data, cfg["max_upload_mb"] * 1024 * 1024)
    obj = StoredObject(
        bucket_id=bucket.id, path=(path or original_name).lstrip("/"), sha256=sha, size=size,
        mime=detect_mime(head, original_name), original_name=original_name,
        uploaded_by=user.id if user else None, metadata_json=json.dumps(metadata or {}),
    )
    session.add(obj)
    session.commit()
    session.refresh(obj)
    actor = user.name if user else "system"
    ledger.append(actor, "storage.upload", {
        "bucket": bucket_name, "object_id": obj.id, "sha256": sha, "size": size,
        "mime": obj.mime, "name": original_name,
    })

    if make_thumbnail and bucket_name != "thumbnails":
        _attach_thumbnail(session, obj, bucket_name, actor)
    return obj


def _attach_thumbnail(session: Session, obj: StoredObject, bucket_name: str, actor: str) -> None:
    from kila.storage.thumbnails import make_thumbnail  # local import: pulls in Pillow/pdfium

    px = get_settings().app["storage"]["thumbnail_px"]
    png = make_thumbnail(blob_path(bucket_name, obj.sha256), obj.mime, px)
    if png is None:
        return
    import io

    thumb = put_object(session, "thumbnails", io.BytesIO(png), f"{obj.id}.png", user=None,
                       path=f"{obj.id}.png", metadata={"thumbnail_of": obj.id}, system=True,
                       make_thumbnail=False)
    meta = json.loads(obj.metadata_json)
    meta["thumbnail_object_id"] = thumb.id
    obj.metadata_json = json.dumps(meta)
    session.add(obj)
    session.commit()
    session.refresh(obj)


def get_object(session: Session, object_id: str, *, include_deleted: bool = False) -> StoredObject:
    obj = session.get(StoredObject, object_id)
    if obj is None or (obj.deleted_at is not None and not include_deleted):
        raise StorageError(404, "object not found")
    return obj


def open_for_read(session: Session, object_id: str, *, actor: str, via: str) -> tuple[StoredObject, Path]:
    obj = get_object(session, object_id)
    bucket_name = bucket_name_of(session, obj)
    p = blob_path(bucket_name, obj.sha256)
    if not p.exists():
        raise StorageError(410, "blob missing on disk")
    if bucket_name not in get_settings().app["storage"].get("unlogged_read_buckets", []):
        ledger.append(actor, "storage.read", {"bucket": bucket_name, "object_id": obj.id,
                                              "sha256": obj.sha256, "via": via})
    return obj, p


def list_objects(session: Session, bucket_name: str, prefix: str = "", limit: int = 500) -> list[StoredObject]:
    bucket = get_bucket(session, bucket_name)
    q = select(StoredObject).where(StoredObject.bucket_id == bucket.id, StoredObject.deleted_at.is_(None))
    if prefix:
        q = q.where(StoredObject.path.startswith(prefix.lstrip("/")))
    return list(session.exec(q.order_by(StoredObject.created_at.desc()).limit(limit)).all())


def soft_delete(session: Session, object_id: str, user: User) -> StoredObject:
    obj = get_object(session, object_id)
    bucket_name = bucket_name_of(session, obj)
    check_access(user, bucket_name, "write")
    obj.deleted_at = utcnow()
    session.add(obj)
    session.commit()
    session.refresh(obj)
    ledger.append(user.name, "storage.delete", {"bucket": bucket_name, "object_id": obj.id,
                                                "sha256": obj.sha256, "soft": True})
    return obj

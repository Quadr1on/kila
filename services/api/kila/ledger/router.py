from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from kila.auth.deps import current_user, require_role
from kila.db.models import User
from kila.ledger import service
from kila.settings import get_settings

router = APIRouter(prefix="/ledger", tags=["ledger"])


class EventOut(BaseModel):
    seq: int
    ts: str
    actor: str
    event_type: str
    payload: Any
    prev_hash: str
    hash: str


class VerifyOut(BaseModel):
    ok: bool
    length: int
    first_bad_seq: int | None
    reason: str | None
    head_hash: str


def _parse(payload_json: str) -> Any:
    try:
        return json.loads(payload_json)
    except json.JSONDecodeError:
        return {"_unparseable": payload_json}


@router.get("/events", response_model=list[EventOut])
def events(
    limit: int = Query(100, ge=1, le=1000),
    before_seq: int | None = None,
    event_type: str | None = None,
    object_id: str | None = None,
    _: User = Depends(current_user),
):
    return [
        EventOut(seq=e.seq, ts=e.ts, actor=e.actor, event_type=e.event_type, payload=_parse(e.payload_json),
                 prev_hash=e.prev_hash, hash=e.hash)
        for e in service.list_events(limit, before_seq, event_type, object_id)
    ]


@router.get("/head")
def head(_: User = Depends(current_user)) -> dict:
    length, h = service.head()
    return {"length": length, "head_hash": h}


@router.get("/verify", response_model=VerifyOut)
def verify(user: User = Depends(current_user)):
    r = service.verify()
    service.append(user.name, "ledger.verify", {"ok": r.ok, "length": r.length, "first_bad_seq": r.first_bad_seq})
    return VerifyOut(ok=r.ok, length=r.length, first_bad_seq=r.first_bad_seq, reason=r.reason, head_hash=r.head_hash)


@router.get("/export")
def export(user: User = Depends(require_role("admin"))) -> dict:
    snap = service.export_signed()
    service.append(user.name, "ledger.export", {"length": snap["manifest"]["length"],
                                                "head_hash": snap["manifest"]["head_hash"]})
    return snap


class TamperIn(BaseModel):
    seq: int


def _tamper_enabled() -> None:
    if not get_settings().app["ledger"].get("tamper_demo_enabled", False):
        raise HTTPException(404, "tamper demo disabled")


@router.post("/debug/tamper")
def tamper(body: TamperIn, user: User = Depends(require_role("admin"))) -> dict:
    _tamper_enabled()
    try:
        result = service.tamper(body.seq)
    except KeyError:
        raise HTTPException(404, f"no ledger event with seq {body.seq}") from None
    # Logged honestly. The appended event is itself valid; the edited row is what verify flags.
    service.append(user.name, "ledger.debug_tamper", {"seq": body.seq})
    return result


@router.post("/debug/restore")
def restore(user: User = Depends(require_role("admin"))) -> dict:
    _tamper_enabled()
    restored = service.restore_tampered()
    service.append(user.name, "ledger.debug_restore", {"seqs": restored})
    return {"restored": restored}

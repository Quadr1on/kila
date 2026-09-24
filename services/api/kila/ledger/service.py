"""Append-only ledger writer, verifier, tamper demo and signed export.

Writes happen in their own short transaction under a process lock. Callers commit their
own work first, then call `append()`. Across processes, the UNIQUE(prev_hash) constraint
and the seq primary key make a forked chain impossible; a losing writer retries.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from kila.db.models import LedgerEvent
from kila.db.session import get_engine
from kila.ledger.chain import GENESIS_HASH, VerifyResult, canonical_json, compute_hash, event_body, verify_rows
from kila.settings import get_settings

_lock = threading.Lock()
_MAX_RETRIES = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def append(actor: str, event_type: str, payload: dict[str, Any] | None = None) -> LedgerEvent:
    payload = payload or {}
    # Round-trip through canonical JSON so what we hash is exactly what we store.
    payload_json = canonical_json(payload)
    payload = json.loads(payload_json)
    with _lock:
        for attempt in range(_MAX_RETRIES):
            with Session(get_engine()) as s:
                last = s.exec(select(LedgerEvent).order_by(LedgerEvent.seq.desc()).limit(1)).first()
                seq = (last.seq if last else 0) + 1
                prev = last.hash if last else GENESIS_HASH
                ts = _now_iso()
                h = compute_hash(prev, event_body(seq, ts, actor, event_type, payload))
                ev = LedgerEvent(seq=seq, ts=ts, actor=actor, event_type=event_type,
                                 payload_json=payload_json, prev_hash=prev, hash=h)
                s.add(ev)
                try:
                    s.commit()
                except IntegrityError:
                    s.rollback()
                    if attempt == _MAX_RETRIES - 1:
                        raise
                    continue
                s.refresh(ev)
                return ev
    raise RuntimeError("unreachable")


def verify() -> VerifyResult:
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT seq, ts, actor, event_type, payload_json, prev_hash, hash FROM ledger_events ORDER BY seq"
        ))
        return verify_rows(tuple(r) for r in rows)


def list_events(limit: int = 100, before_seq: int | None = None, event_type: str | None = None,
                object_id: str | None = None) -> list[LedgerEvent]:
    with Session(get_engine()) as s:
        q = select(LedgerEvent)
        if before_seq is not None:
            q = q.where(LedgerEvent.seq < before_seq)
        if event_type:
            q = q.where(LedgerEvent.event_type == event_type)
        if object_id:
            q = q.where(func.json_extract(LedgerEvent.payload_json, "$.object_id") == object_id)
        return list(s.exec(q.order_by(LedgerEvent.seq.desc()).limit(limit)).all())


def head() -> tuple[int, str]:
    """(length, head hash) without verifying. Cheap; for status displays."""
    with Session(get_engine()) as s:
        last = s.exec(select(LedgerEvent).order_by(LedgerEvent.seq.desc()).limit(1)).first()
        return (last.seq, last.hash) if last else (0, GENESIS_HASH)


# ---------------------------------------------------------------- tamper demo

def _backup_path() -> Path:
    return get_settings().data_dir / "tamper_backup.json"


def tamper(seq: int) -> dict[str, Any]:
    """Edit one row directly in SQLite, bypassing the writer. Demo only."""
    with get_engine().begin() as conn:
        row = conn.execute(text("SELECT payload_json FROM ledger_events WHERE seq=:s"), {"s": seq}).first()
        if row is None:
            raise KeyError(seq)
        original = row[0]
        payload = json.loads(original)
        payload["_tampered"] = "this row was edited directly in SQLite"
        conn.execute(text("UPDATE ledger_events SET payload_json=:p WHERE seq=:s"),
                     {"p": canonical_json(payload), "s": seq})
    backups = _read_backups()
    backups.setdefault(str(seq), original)  # keep the first (true) original
    _backup_path().write_text(json.dumps(backups), encoding="utf-8")
    return {"seq": seq, "original_payload_json": original}


def restore_tampered() -> list[int]:
    backups = _read_backups()
    with get_engine().begin() as conn:
        for seq, original in backups.items():
            conn.execute(text("UPDATE ledger_events SET payload_json=:p WHERE seq=:s"),
                         {"p": original, "s": int(seq)})
    _backup_path().unlink(missing_ok=True)
    return sorted(int(k) for k in backups)


def _read_backups() -> dict[str, str]:
    p = _backup_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------------------------------------------------------------- signed export

def _signing_key() -> Ed25519PrivateKey:
    keys = get_settings().keys_dir
    keys.mkdir(parents=True, exist_ok=True)
    path = keys / "ledger_ed25519.pem"
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[return-value]
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    return key


def public_key_b64() -> str:
    raw = _signing_key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def export_signed() -> dict[str, Any]:
    with get_engine().connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(text(
            "SELECT seq, ts, actor, event_type, payload_json, prev_hash, hash FROM ledger_events ORDER BY seq"))]
    result = verify_rows((r["seq"], r["ts"], r["actor"], r["event_type"], r["payload_json"],
                          r["prev_hash"], r["hash"]) for r in rows)
    manifest = {
        "exported_at": _now_iso(),
        "length": len(rows),
        "head_hash": rows[-1]["hash"] if rows else GENESIS_HASH,
        "verify_ok": result.ok,
        "first_bad_seq": result.first_bad_seq,
        "events_sha256": hashlib.sha256(canonical_json(rows).encode("utf-8")).hexdigest(),
    }
    sig = _signing_key().sign(canonical_json(manifest).encode("utf-8"))
    return {
        "manifest": manifest,
        "signature_ed25519_b64": base64.b64encode(sig).decode(),
        "public_key_ed25519_b64": public_key_b64(),
        "events": rows,
    }

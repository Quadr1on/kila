"""Pure hash-chain functions (no DB). hash_n = SHA256(hash_{n-1} || canonical_json(event_n))."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

GENESIS_HASH = hashlib.sha256(b"KILA-GENESIS").hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 (non-ASCII kept as-is)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def event_body(seq: int, ts: str, actor: str, event_type: str, payload: Any) -> dict[str, Any]:
    # seq is part of the hashed body so rows cannot be reordered or renumbered undetected.
    return {"seq": seq, "ts": ts, "actor": actor, "event_type": event_type, "payload": payload}


def compute_hash(prev_hash: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(body)).encode("utf-8")).hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    length: int
    first_bad_seq: int | None = None
    reason: str | None = None
    head_hash: str = GENESIS_HASH


def verify_rows(rows: Iterable[tuple[int, str, str, str, str, str, str]]) -> VerifyResult:
    """rows: (seq, ts, actor, event_type, payload_json, prev_hash, hash) ordered by seq."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    length = 0
    bad: tuple[int, str] | None = None
    for seq, ts, actor, event_type, payload_json, prev_hash, stored_hash in rows:
        length += 1
        if bad is not None:
            continue  # keep counting so `length` is the full chain length
        problem = _check_row(seq, ts, actor, event_type, payload_json, prev_hash, stored_hash,
                             expected_seq, expected_prev)
        if problem:
            bad = (seq, problem)
            continue
        expected_prev = stored_hash
        expected_seq += 1
    if bad:
        return VerifyResult(False, length, bad[0], bad[1], expected_prev)
    return VerifyResult(True, length, None, None, expected_prev)


def _check_row(seq, ts, actor, event_type, payload_json, prev_hash, stored_hash,
               expected_seq, expected_prev) -> str | None:  # noqa: ANN001
    if seq != expected_seq:
        return f"sequence gap: expected {expected_seq}, got {seq}"
    if prev_hash != expected_prev:
        return "prev_hash does not match previous event's hash"
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return "payload is not valid JSON"
    if compute_hash(prev_hash, event_body(seq, ts, actor, event_type, payload)) != stored_hash:
        return "hash mismatch: event content was modified"
    return None

from __future__ import annotations

import json

from kila.ledger import service
from kila.ledger.chain import GENESIS_HASH, canonical_json, compute_hash, event_body, verify_rows


def _chain(n: int) -> list[tuple]:
    rows, prev = [], GENESIS_HASH
    for i in range(1, n + 1):
        payload = {"i": i, "text": "पाइपलाइन निरीक्षण"}  # non-ASCII must hash stably
        ts = f"2026-01-01T00:00:{i:02d}+00:00"
        h = compute_hash(prev, event_body(i, ts, "t", "e", payload))
        rows.append((i, ts, "t", "e", canonical_json(payload), prev, h))
        prev = h
    return rows


def test_genesis_is_sha256_of_constant():
    import hashlib

    assert GENESIS_HASH == hashlib.sha256(b"KILA-GENESIS").hexdigest()


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == canonical_json({"a": [1, {"c": 3, "d": 2}], "b": 1})


def test_valid_chain_verifies():
    r = verify_rows(_chain(5))
    assert r.ok and r.length == 5 and r.first_bad_seq is None
    assert r.head_hash == _chain(5)[-1][6]


def test_empty_chain_verifies():
    r = verify_rows([])
    assert r.ok and r.length == 0 and r.head_hash == GENESIS_HASH


def test_modified_payload_detected_at_exact_seq():
    rows = _chain(6)
    seq, ts, actor, et, _, prev, h = rows[3]
    rows[3] = (seq, ts, actor, et, canonical_json({"i": 999}), prev, h)
    r = verify_rows(rows)
    assert not r.ok and r.first_bad_seq == 4 and r.length == 6


def test_deleted_row_detected():
    rows = _chain(5)
    del rows[2]
    r = verify_rows(rows)
    assert not r.ok and r.first_bad_seq == 4  # gap: expected 3, got 4


def test_recomputed_hash_breaks_next_link():
    """An attacker who edits a row AND fixes its hash still breaks the following row's prev_hash."""
    rows = _chain(5)
    seq, ts, actor, et, _, prev, _ = rows[1]
    new_payload = {"i": 2, "forged": True}
    new_hash = compute_hash(prev, event_body(seq, ts, actor, et, new_payload))
    rows[1] = (seq, ts, actor, et, canonical_json(new_payload), prev, new_hash)
    r = verify_rows(rows)
    assert not r.ok and r.first_bad_seq == 3


def test_service_append_verify_tamper_restore(app_env):
    for i in range(5):
        service.append("tester", "test.event", {"i": i})
    assert service.verify().ok

    target = service.list_events(limit=1)[0].seq - 2
    service.tamper(target)
    r = service.verify()
    assert not r.ok and r.first_bad_seq == target

    # Appends after a tamper still chain on the stored hashes; the break stays at `target`.
    service.append("tester", "test.after", {})
    assert service.verify().first_bad_seq == target

    assert service.restore_tampered() == [target]
    assert service.verify().ok


def test_signed_export_verifies(app_env):
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    service.append("tester", "test.event", {"x": 1})
    snap = service.export_signed()
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(snap["public_key_ed25519_b64"]))
    pub.verify(base64.b64decode(snap["signature_ed25519_b64"]),
               canonical_json(snap["manifest"]).encode())  # raises if invalid
    assert snap["manifest"]["verify_ok"] and snap["manifest"]["length"] == len(snap["events"])


def test_ledger_api_roles(client_for):
    eng = client_for("engineer")
    admin = client_for("admin")
    assert eng.get("/ledger/verify").json()["ok"] is True
    assert eng.post("/ledger/debug/tamper", json={"seq": 1}).status_code == 403
    assert eng.get("/ledger/export").status_code == 403

    assert admin.post("/ledger/debug/tamper", json={"seq": 2}).status_code == 200
    v = admin.get("/ledger/verify").json()
    assert v["ok"] is False and v["first_bad_seq"] == 2
    admin.post("/ledger/debug/restore")
    assert admin.get("/ledger/verify").json()["ok"] is True

    types = [e["event_type"] for e in eng.get("/ledger/events?limit=1000").json()]
    assert "auth.login" in types and "ledger.debug_tamper" in types and json.dumps(types)


def test_concurrent_appends_keep_chain_valid(app_env):
    from concurrent.futures import ThreadPoolExecutor

    before = service.verify().length
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: service.append("t", "test.concurrent", {"i": i}), range(80)))
    r = service.verify()
    assert r.ok and r.length == before + 80

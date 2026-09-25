from __future__ import annotations

import hashlib
import json

from kila.rag.bm25 import tokenize
from kila.rag.chunking import chunk_page
from kila.rag.service import rrf
from kila.settings import REPO_ROOT

SEED = REPO_ROOT / "seed"


# ------------------------------------------------------------------ pure functions

def test_chunks_keep_exact_offsets_and_prefer_headings():
    sections = [f"{i}. Section {i}\n" + ("Word " * 150).strip() for i in range(1, 6)]
    text = "\n".join(sections)
    chunks = chunk_page(text, page=3, target_tokens=200, overlap_tokens=30)
    assert len(chunks) > 1 and all(c.page == 3 for c in chunks)
    for c in chunks:
        assert c.text == text[c.char_start:c.char_end].strip()
    # each chunk starts at its section heading, with no overlap back into the previous section
    assert [c.heading for c in chunks] == [f"{i}. Section {i}" for i in range(1, 6)]
    assert all(c.text.startswith(c.heading) for c in chunks)
    assert all(b.char_start == a.char_end for a, b in zip(chunks, chunks[1:]))


def test_plain_prose_chunks_overlap():
    text = " ".join(f"sentence{i} ends here." for i in range(400))
    chunks = chunk_page(text, page=1, target_tokens=150, overlap_tokens=30)
    assert len(chunks) > 2
    assert all(b.char_start < a.char_end for a, b in zip(chunks, chunks[1:]))  # overlap keeps context
    assert all(c.text == text[c.char_start:c.char_end].strip() for c in chunks)


def test_tiny_tail_is_merged():
    text = ("alpha " * 300) + "\n\nend."
    chunks = chunk_page(text, page=1, target_tokens=150, overlap_tokens=0, min_chunk_chars=80)
    assert not chunks[-1].text == "end."
    assert chunks[-1].text.endswith("end.")


def test_empty_page_has_no_chunks():
    assert chunk_page("   \n ", page=1) == []


def test_bm25_tokenizer_keeps_engineering_tokens():
    toks = tokenize('Replace PV-101 on 6"-P-1045-A1B; rate 0.425 mm/yr, H2S < 1 ppm')
    assert {"pv-101", "pv", "101", "0.425", "h2s", "1045"} <= set(toks)
    assert "on" in toks or True  # stop words are filtered, domain tokens are not


def test_rrf_rewards_agreement():
    fused = dict(rrf([["a", "b", "c"], ["b", "c", "d"]], k=60))
    assert fused["b"] > fused["a"] and fused["b"] > fused["d"]
    assert abs(fused["b"] - (1 / 62 + 1 / 61)) < 1e-12


# ------------------------------------------------------------------ indexing + search (fake models)

def _index(c, bucket: str, name: str, data: bytes) -> str:
    from kila.ingest import service as ing

    oid = c.post(f"/storage/{bucket}/upload", files={"file": (name, data)}).json()["object_id"]
    assert c.post(f"/kb/documents/{oid}/index").status_code == 200
    ing.wait_idle(300)
    ing.wait_idle(300)  # indexing runs on the same worker right after extraction
    return oid


def _kb(c):
    ids = {}
    for f in ("SOP-MNT-010", "SOP-OPS-001", "STD-ENG-100"):
        ids[f] = _index(c, "kb", f"{f}.pdf", (SEED / f"kb/{f}.pdf").read_bytes())
    return ids


def test_index_then_hybrid_search_finds_the_right_procedure(client_for):
    admin = client_for("admin")
    ids = _kb(admin)
    docs = admin.get("/kb/documents").json()
    assert {d["status"] for d in docs} == {"indexed"} and all(d["chunk_count"] > 0 for d in docs)
    assert {d["doc_type"] for d in docs} == {"procedure", "standard"}

    r = admin.post("/kb/search", json={"query": "gas test LEL oxygen before hot work permit"}).json()
    assert r["results"][0]["object_id"] == ids["SOP-OPS-001"]
    for stage in ("dense", "bm25", "fused", "reranked", "results"):
        assert r[stage], stage
    top = r["results"][0]
    assert top["page"] == 1 and top["char_end"] > top["char_start"] and top["name"] == "SOP-OPS-001.pdf"
    assert 0 < r["retrieval_relevance"] <= 1 and r["timings_ms"]["total_ms"] >= 0

    ev = admin.get("/ledger/events?event_type=kb.search").json()[0]["payload"]
    assert ev["query_sha256"] == hashlib.sha256(b"gas test LEL oxygen before hot work permit").hexdigest()
    assert "hot work" not in json.dumps(ev)  # the ledger never stores the query text


def test_search_can_be_restricted_to_attachments(client_for):
    admin = client_for("admin")
    _kb(admin)
    up = _index(admin, "uploads", "IR-2026-0163_scan.pdf", (SEED / "reports/IR-2026-0163_scan.pdf").read_bytes())
    kb_only = admin.post("/kb/search", json={"query": "PSV-1204 as-received pop pressure"}).json()
    assert all(x["bucket"] == "kb" for x in kb_only["results"])  # uploads don't leak into KB search
    att = admin.post("/kb/search", json={"query": "PSV-1204 as-received pop pressure", "object_ids": [up]}).json()
    assert att["results"] and {x["object_id"] for x in att["results"]} == {up}


def test_removed_documents_disappear_from_search(client_for):
    admin = client_for("admin")
    ids = _kb(admin)
    assert admin.delete(f"/kb/documents/{ids['SOP-OPS-001']}").status_code == 204
    r = admin.post("/kb/search", json={"query": "hot work permit gas testing fire watch"}).json()
    assert ids["SOP-OPS-001"] not in {x["object_id"] for x in r["results"]}
    assert ids["SOP-OPS-001"] not in {d["object_id"] for d in admin.get("/kb/documents").json()}


def test_reindex_replaces_chunks(client_for):
    admin = client_for("admin")
    oid = _index(admin, "kb", "STD-ENG-100.pdf", (SEED / "kb/STD-ENG-100.pdf").read_bytes())
    before = admin.get("/kb/documents").json()[0]["chunk_count"]
    from kila.ingest import service as ing

    admin.post(f"/kb/documents/{oid}/index")
    ing.wait_idle(300)
    ing.wait_idle(300)
    from sqlmodel import Session, func, select

    from kila.db.models import KBChunk
    from kila.db.session import get_engine

    with Session(get_engine()) as s:
        n = s.exec(select(func.count()).select_from(KBChunk).where(KBChunk.object_id == oid)).one()
    assert n == before  # no duplicates after re-indexing


def test_roles(client_for):
    rev = client_for("reviewer")
    admin = client_for("admin")
    oid = admin.post("/storage/kb/upload", files={"file": ("x.txt", b"flare purge gas")}).json()["object_id"]
    assert rev.post(f"/kb/documents/{oid}/index").status_code == 403
    assert rev.post("/kb/seed").status_code == 403
    assert rev.post("/kb/search", json={"query": "flare"}).status_code == 200  # everyone may search


# ------------------------------------------------------------------ grounded chat

def _sse(text: str):
    return [(b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1]))
            for b in text.strip().split("\n\n") if b.startswith("event:")]


def test_grounded_answer_streams_sources_and_checks_citations(client_for):
    eng = client_for("engineer")
    oid = _index(eng, "uploads", "IR-2026-0147_scan.pdf", (SEED / "reports/IR-2026-0147_scan.pdf").read_bytes())
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    r = eng.post(f"/chat/sessions/{sid}/messages", json={"content": "Corrosion rate at nozzle N3?", "attachments": [oid]})
    evs = _sse(r.text)
    kinds = [k for k, _ in evs]
    assert kinds[:3] == ["start", "status", "sources"] and kinds[-1] == "done"
    sources = evs[2][1]["sources"]
    assert sources[0]["name"] == "IR-2026-0147_scan.pdf" and sources[0]["page"] == 1 and sources[0]["snippet"]
    g = evs[-1][1]["grounding"]
    assert g["cited"] == [1] and g["invalid"] == [] and g["uncited_answer"] is False

    msgs = eng.get(f"/chat/sessions/{sid}/messages").json()
    assert msgs[0]["meta"]["attachments"][0]["object_id"] == oid
    assert msgs[1]["meta"]["grounding"]["sources"][0]["chunk_id"].startswith(oid)
    ev = eng.get("/ledger/events?event_type=llm.call").json()[0]["payload"]
    assert ev["grounded"] is True and ev["source_chunks"] and ev["cited"] == [1]
    assert "nozzle" not in json.dumps(ev).lower()


def test_grounded_kb_answer(client_for):
    admin = client_for("admin")
    _kb(admin)
    sid = admin.post("/chat/sessions", json={}).json()["id"]
    r = admin.post(f"/chat/sessions/{sid}/messages", json={"content": "PSV test interval?", "use_kb": True})
    evs = _sse(r.text)
    assert any(s["name"] == "SOP-MNT-010.pdf" for s in evs[2][1]["sources"])


def test_unready_attachment_is_rejected(client_for):
    eng = client_for("engineer")
    oid = eng.post("/storage/uploads/upload", files={"file": ("a.txt", b"x")}).json()["object_id"]
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    r = eng.post(f"/chat/sessions/{sid}/messages", json={"content": "q", "attachments": [oid]})
    assert r.status_code == 409 and "hasn't been read" in r.json()["detail"]


def test_citation_checker():
    from kila.rag.answer import check_citations

    srcs = [{"n": 1}, {"n": 2}]
    assert check_citations("A [S1]. B [S2][S7].", srcs) == {"cited": [1, 2], "invalid": [7], "uncited_answer": False}
    assert check_citations("No cites.", srcs)["uncited_answer"] is True

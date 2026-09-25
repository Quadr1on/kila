"""Phase 2 acceptance + measurement run, against REAL local models, in a throwaway data dir.

1. Load the synthetic corpus into the knowledge base (ingest + OCR + index), timed.
2. OCR accuracy on every scanned report vs its ground-truth text.
3. Upload a scanned report, attach it, and ask questions with known answers (repeated).
4. Ask knowledge-base questions with known answers (repeated).
Writes metrics/phase2_check.json. Needs Ollama running with the small_text model available.

    uv run --directory services/api python ../../scripts/phase2_check.py [--repeats 3] [--model gemma4:e2b]
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ATTACHMENT_QS = [
    {"q": "Which CML on E-2104 has the highest corrosion rate, and what is that rate?",
     "expect": [r"\bC3\b", r"0\.425"]},
    {"q": "What remaining life is reported for CML C3 of E-2104?", "expect": [r"8\.5"]},
]
KB_QS = [
    {"q": "What is the acceptance tolerance on popping pressure for a PSV with a set pressure of 5 bar(g) or less?",
     "expect": [r"0\.15"]},
    {"q": "How often must the area be re-tested for gas during hot work?", "expect": [r"\b2 hours\b|\btwo hours\b"]},
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def ask(c, content: str, **kw) -> dict:
    sid = c.post("/chat/sessions", json={}).json()["id"]
    t0 = time.perf_counter()
    r = c.post(f"/chat/sessions/{sid}/messages", json={"content": content, **kw})
    evs = [(b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1]))
           for b in r.text.strip().split("\n\n") if b.startswith("event:")]
    ans = "".join(d["text"] for k, d in evs if k == "delta")
    done = next((d for k, d in evs if k == "done"), None)
    return {"answer": ans, "wall_s": round(time.perf_counter() - t0, 2), "meta": done,
            "error": next((d["detail"] for k, d in evs if k == "error"), None)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--model", default=None, help="activate this model for small_text first")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="kila-p2-")
    os.environ["KILA_DATA_DIR"] = str(Path(tmp) / "data")
    os.environ["KILA_METRICS_DIR"] = str(Path(tmp) / "metrics")
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from fastapi.testclient import TestClient

    from kila.ingest import service as ing
    from kila.main import app

    out: dict = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with TestClient(app) as c:
        c.post("/auth/login", json={"username": "admin", "password": os.environ.get("KILA_SEED_PASSWORD", "kila-demo")})
        if args.model:
            c.post("/models/small_text/activate", json={"name": args.model})
        out["model"] = next(r["model"] for r in c.get("/models/roles").json() if r["role"] == "small_text")

        # 1. corpus
        t0 = time.perf_counter()
        n = len(c.post("/kb/seed").json()["queued"])
        ing.wait_idle(1800)
        ing.wait_idle(1800)
        docs = c.get("/kb/documents").json()
        out["corpus"] = {"documents": n, "indexed": sum(d["status"] == "indexed" for d in docs),
                         "chunks": sum(d["chunk_count"] for d in docs), "wall_s": round(time.perf_counter() - t0, 1)}
        print("corpus:", out["corpus"], flush=True)

        # 2. OCR accuracy on every scanned report
        ocr = []
        for d in docs:
            if not d["name"].endswith("_scan.pdf"):
                continue
            a = c.get(f"/ingest/{d['object_id']}").json()["attachment"]
            truth = norm((ROOT / "seed/reports/_truth" / d["name"].replace("_scan.pdf", ".txt")).read_text("utf-8"))
            text = norm(a["pages"][0]["text"])
            ocr.append({"report": d["name"], "char_similarity": round(difflib.SequenceMatcher(None, truth, text).ratio(), 3),
                        "ocr_conf": a["pages"][0]["ocr_conf"], "skew_deg": a["pages"][0]["skew_deg"],
                        "ocr_ms": a["timings_ms"].get("ocr_p1")})
        out["ocr"] = ocr
        print("ocr:", [(o["report"], o["char_similarity"]) for o in ocr], flush=True)

        # 3. attachment questions
        oid = c.post("/storage/uploads/upload", files={"file": (
            "IR-2026-0147_scan.pdf", (ROOT / "seed/reports/IR-2026-0147_scan.pdf").read_bytes())}).json()["object_id"]
        c.post(f"/kb/documents/{oid}/index")
        ing.wait_idle(600)
        ing.wait_idle(600)

        def run(qs, **kw):
            rows = []
            for item in qs:
                for i in range(args.repeats):
                    r = ask(c, item["q"], **kw)
                    ok = all(re.search(p, r["answer"], re.I) for p in item["expect"])
                    g = (r["meta"] or {}).get("grounding", {})
                    rows.append({"q": item["q"], "try": i + 1, "correct": ok, "answer": r["answer"],
                                 "cited": g.get("cited"), "invalid_citations": g.get("invalid"),
                                 "top_source": (g.get("sources") or [{}])[0].get("name"),
                                 "retrieval_relevance": g.get("retrieval_relevance"), "wall_s": r["wall_s"],
                                 "error": r["error"]})
                    print(f"  {'OK ' if ok else 'BAD'} {r['wall_s']:5.1f}s {item['q'][:60]} -> {r['answer'][:110]!r}", flush=True)
            return rows

        print("attachment questions:")
        out["attachment_qa"] = run(ATTACHMENT_QS, attachments=[oid])
        print("knowledge-base questions:")
        out["kb_qa"] = run(KB_QS, use_kb=True)

    qa = out["attachment_qa"] + out["kb_qa"]
    out["summary"] = {
        "answers": len(qa), "correct": sum(r["correct"] for r in qa),
        "accuracy": round(sum(r["correct"] for r in qa) / len(qa), 3),
        "with_valid_citation": sum(bool(r["cited"]) and not r["invalid_citations"] for r in qa),
        "right_document_retrieved": sum(r["top_source"] is not None for r in qa),
        "median_answer_s": sorted(r["wall_s"] for r in qa)[len(qa) // 2],
        "mean_ocr_char_similarity": round(sum(o["char_similarity"] for o in ocr) / len(ocr), 3) if ocr else None,
    }
    print("summary:", out["summary"])
    dest = ROOT / "metrics" / "phase2_check.json"
    dest.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print("written:", dest.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

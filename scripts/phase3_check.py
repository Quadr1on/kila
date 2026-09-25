"""Phase 3 acceptance run on REAL models in a throwaway data dir.

Routes 20 mixed prompts (English, Hindi, Kannada; with and without attachments; knowledge-base
questions the corpus does and doesn't cover). For knowledge-base prompts the retrieval relevance
comes from a real hybrid search over the synthetic corpus, so low-relevance escalation is real.
Two prompts also go through the full auto-routed chat. Writes metrics/phase3_check.json.

    uv run --directory services/api python ../../scripts/phase3_check.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (prompt, expected task type, attachment kinds, ask the knowledge base?)
PROMPTS = [
    ("What is the PSV test interval?", "general_qa", [], True),
    ("How often must the area be re-tested for gas during hot work?", "general_qa", [], True),
    ("What is the corrosion allowance for carbon steel in amine service?", "general_qa", [], True),
    ("What torque do the reactor head bolts on R-9901 need?", "general_qa", [], True),
    ("What does our SOP say about helicopter landing on the tank farm?", "general_qa", [], True),
    ("Draft an approval note recommending re-inspection of E-2104 based on the attached report",
     "approval_note", ["pdf_scanned"], False),
    ("Calculate the remaining life of CML C3: t_actual 9.8 mm, t_min 6.2 mm, rate 0.425 mm/yr",
     "engineering_calc", [], False),
    ("Check the PSV sizing for PSV-1204 relieving 12,000 kg/h of hydrocarbon vapour", "engineering_calc", [], False),
    ("Fix the bug in this python function that computes the corrosion rate", "code_task", ["code"], False),
    ("Digitise the attached P&ID and list all instrument tags", "pid_digitise", ["image"], False),
    ("Reply to Deccan Valves asking for a revised quotation for PSV spares", "correspondence", [], False),
    ("Which PSVs in the attached register are overdue for testing?", "sheet_analysis", ["sheet"], False),
    ("Summarise the findings of the attached inspection report", "inspection_summary", ["pdf_scanned"], False),
    ("something is off with the pump, what now", "general_qa", [], False),
    ("इस निरीक्षण रिपोर्ट का सारांश बनाइए", "inspection_summary", ["pdf_scanned"], False),
    ("PSV परीक्षण का अंतराल क्या है?", "general_qa", [], True),
    ("ಈ ತಪಾಸಣಾ ವರದಿಯ ಸಾರಾಂಶ ನೀಡಿ", "inspection_summary", ["pdf_scanned"], False),
    ("ಹಾಟ್ ವರ್ಕ್ ಸಮಯದಲ್ಲಿ ಅನಿಲ ಪರೀಕ್ಷೆಯನ್ನು ಎಷ್ಟು ಬಾರಿ ಮಾಡಬೇಕು?", "general_qa", [], True),
    ("Compare corrosion trends across all exchangers and recommend which to open at the next turnaround",
     "approval_note", ["sheet"], False),
    ("Write a letter to Malabar Pumps rejecting the delivery because the test certificates are missing",
     "correspondence", [], False),
]


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:e2b", help="activate this model for small_text and vision first")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="kila-p3-")
    os.environ["KILA_DATA_DIR"] = str(Path(tmp) / "data")
    os.environ["KILA_METRICS_DIR"] = str(Path(tmp) / "metrics")
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from fastapi.testclient import TestClient

    from kila.ingest import service as ing
    from kila.main import app

    rows = []
    with TestClient(app) as c:
        c.post("/auth/login", json={"username": "admin", "password": os.environ.get("KILA_SEED_PASSWORD", "kila-demo")})
        if args.model:  # a fresh data dir starts on the profile defaults, which may not be downloaded
            for role in ("small_text", "vision"):
                c.post(f"/models/{role}/activate", json={"name": args.model})
        print("loading the synthetic corpus for real retrieval relevance...", flush=True)
        c.post("/kb/seed")
        ing.wait_idle(1800)
        ing.wait_idle(1800)
        for i, (text, gold, kinds, kb) in enumerate(PROMPTS, 1):
            rel = None
            if kb:
                s = c.post("/kb/search", json={"query": text}).json()
                rel = s["retrieval_relevance"]
            t0 = time.perf_counter()
            d = c.post("/router/route", json={"text": text, "attachment_kinds": kinds, "retrieval_relevance": rel}).json()
            wall = round((time.perf_counter() - t0) * 1000)
            ok = d.get("task_type") == gold
            rows.append({"prompt": text, "expected": gold, "attachments": kinds, "retrieval_relevance": rel,
                         "correct_task": ok, "wall_ms": wall,
                         **{k: d.get(k) for k in ("task_type", "task_conf", "difficulty", "needs_vision", "score", "tau",
                                                  "chosen_role", "chosen_model", "escalated", "escalation_reasons",
                                                  "escalation_blocked", "summary")},
                         "checkpoint": (d.get("classifier") or {}).get("checkpoint")})
            flag = "OK " if ok else "BAD"
            esc = "ESCALATE" if d.get("escalation_reasons") and d.get("base_role") == "small_text" else ""
            print(f"{i:2}. {flag} {esc:8} {d.get('summary')}\n      {text[:90]}", flush=True)

        print("\nend-to-end auto-routed chats:", flush=True)
        chats = []
        for text, kw in (("What is the PSV test interval?", {"use_kb": True}), ("Convert 12.5 bar(g) to kPa absolute", {})):
            sid = c.post("/chat/sessions", json={}).json()["id"]
            r = c.post(f"/chat/sessions/{sid}/messages", json={"content": text, **kw})
            evs = [(b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1]))
                   for b in r.text.strip().split("\n\n") if b.startswith("event:")]
            route = next((d for k, d in evs if k == "route"), {})
            done = next((d for k, d in evs if k == "done"), {})
            answer = "".join(d["text"] for k, d in evs if k == "delta")
            err = next((d.get("detail") for k, d in evs if k == "error"), None)
            chats.append({"prompt": text, "events": [k for k, _ in evs], "route": route.get("summary"),
                          "answered_by": done.get("model"), "answer": answer[:300], "error": err})
            print(f"  {route.get('summary')}\n  -> {done.get('model')}: {answer[:120]!r}", flush=True)
        stats = c.get("/router/stats").json()

    n = len(rows)
    wanted = [r for r in rows if r["escalation_reasons"] and r["chosen_role"] in ("small_text", "large_text")]
    summary = {
        "prompts": n,
        "task_type_correct": sum(r["correct_task"] for r in rows),
        "escalation_wanted": len(wanted),
        "escalated": sum(bool(r["escalated"]) for r in rows),
        "escalation_blocked_no_large_model": sum(bool(r["escalation_blocked"]) and "available" in r["escalation_blocked"]
                                                 for r in rows),
        # knowledge-base prompts whose best passage scored < 0.6 (the corpus doesn't cover them)
        "low_relevance_prompts_escalation_wanted": sum(1 for r in wanted if r["retrieval_relevance"] is not None
                                                       and r["retrieval_relevance"] < 0.6),
        "median_route_ms": sorted(r["wall_ms"] for r in rows)[n // 2],
    }
    out = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "summary": summary, "rows": rows,
           "chats": chats, "router_stats_after": stats}
    dest = ROOT / "metrics" / "phase3_check.json"
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("\nsummary:", summary)
    print("written:", dest.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

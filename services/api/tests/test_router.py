from __future__ import annotations

import json
import random
import re
import shutil

import pytest

from kila.settings import REPO_ROOT


@pytest.fixture()
def pinned(tmp_path, monkeypatch, app_env):
    """A private copy of config/ with tau=0.70, alpha=0.5 and T=1, so recalibrating never changes these tests."""
    from kila.router import cascade
    from kila.settings import get_settings, load_app_config

    cfg = tmp_path / "cfg"
    shutil.copytree(REPO_ROOT / "config", cfg)
    y = (cfg / "router.yaml").read_text(encoding="utf-8")
    y = re.sub(r"(?m)^(  (task_type|difficulty|needs_vision): )[0-9.]+$", r"\g<1>1.0", y)
    y = re.sub(r"(?m)^(  tau: )[0-9.]+", r"\g<1>0.70", y)
    y = re.sub(r"(?m)^(  alpha: )[0-9.]+", r"\g<1>0.5", y)
    (cfg / "router.yaml").write_text(y, encoding="utf-8")
    monkeypatch.setenv("KILA_CONFIG_DIR", str(cfg))
    get_settings.cache_clear()
    load_app_config.cache_clear()
    cascade.clear_availability_cache()
    return cfg


# ------------------------------------------------------------------ calibration maths

def test_temperature_scaling_properties():
    from kila.router.classifier import apply_temperature

    p = {"a": 0.9, "b": 0.08, "c": 0.02}
    assert apply_temperature(p, 1.0) == p
    soft = apply_temperature(p, 3.0)
    assert abs(sum(soft.values()) - 1) < 1e-9 and max(soft, key=soft.get) == "a" and soft["a"] < 0.9
    sharp = apply_temperature(p, 0.5)
    assert sharp["a"] > 0.9


def test_fit_temperature_recovers_overconfidence():
    """Sharpen honest probabilities with T=1/3; the fit should find T close to 3 and cut ECE."""
    from kila.router.calibrate import ece, fit_temperature
    from kila.router.classifier import apply_temperature

    rng = random.Random(0)
    rows = []
    for _ in range(600):
        truth = rng.choice("abc")
        honest = {k: (0.6 if k == truth else 0.2) for k in "abc"}
        if rng.random() < 0.4:  # 40% of the time the model's belief is wrong
            wrong = rng.choice([k for k in "abc" if k != truth])
            honest = {k: (0.6 if k == wrong else 0.2) for k in "abc"}
        rows.append({"probs": {"task_type": apply_temperature(honest, 1 / 3)}, "task_type": truth})
    t = fit_temperature(rows, "task_type")
    assert 2.4 <= t <= 3.6
    conf = lambda T: [max(apply_temperature(r["probs"]["task_type"], T).values()) for r in rows]  # noqa: E731
    right = [max(r["probs"]["task_type"], key=r["probs"]["task_type"].get) == r["task_type"] for r in rows]
    assert ece(conf(t), right) < ece(conf(1.0), right) / 3


def test_ece_perfectly_calibrated_is_zero():
    from kila.router.calibrate import ece

    assert ece([0.8] * 10, [True] * 8 + [False] * 2) == 0.0


def test_labelled_set_is_balanced_and_multilingual():
    rows = [json.loads(line) for line in (REPO_ROOT / "seed/router_labels.jsonl").read_text("utf-8").splitlines()]
    assert 200 <= len(rows) <= 400
    by_task = {r["task_type"] for r in rows}
    assert len(by_task) == 8
    assert {r["lang"] for r in rows} == {"en", "hi", "kn"}
    assert all(r["difficulty"] in ("low", "medium", "high") for r in rows)


# ------------------------------------------------------------------ cascade decisions

def test_confident_routine_request_stays_small(pinned):
    from kila.router.cascade import decide

    d = decide("What is the PSV test interval?")
    assert d["task_type"] == "general_qa" and d["chosen_role"] == "small_text" and not d["escalated"]
    assert d["score"] == d["task_conf"] == 0.9 and d["alpha"] == 1.0  # no retrieval: score = task confidence
    assert "general_qa · conf 0.90 · relevance — · score 0.90 ≥ τ 0.70 → small_text" == d["summary"]


def test_low_confidence_escalates(pinned):
    from kila.router.cascade import decide

    d = decide("something vague about the unit")
    assert d["score"] == 0.3 and d["chosen_role"] == "large_text" and d["escalated"]
    assert d["chosen_model"] == "qwen3:8b" and any("< τ" in r for r in d["escalation_reasons"])


def test_high_difficulty_escalates(pinned):
    from kila.router.cascade import decide

    d = decide("Draft an approval note for the seal replacement")
    assert d["task_type"] == "approval_note" and d["difficulty"] == "high"
    assert d["escalated"] and any("high difficulty" in r for r in d["escalation_reasons"])


def test_retrieval_relevance_is_blended(pinned):
    from kila.router.cascade import decide

    good = decide("What is the PSV test interval?", retrieval_relevance=0.8)
    assert good["score"] == pytest.approx(0.5 * 0.9 + 0.5 * 0.8) and not good["escalated"]
    poor = decide("What is the PSV test interval?", retrieval_relevance=0.2)  # 0.55 < 0.70: documents don't cover it
    assert poor["score"] == pytest.approx(0.55) and poor["escalated"]


def test_specialist_roles(pinned):
    from kila.router.cascade import decide

    code = decide("urgent: fix this python code")
    assert code["chosen_role"] == "coder" and not code["escalated"]
    assert "specialist" in code["escalation_blocked"]
    pid = decide("Digitise the attached P&ID", [{"kind": "image", "name": "p.png"}])
    assert pid["chosen_role"] == "vision" and pid["needs_vision"] and pid["vision_source"] == "attachment"


def test_scan_attachment_is_perceived_at_ingestion_then_answered_by_text_model(pinned):
    from kila.router.cascade import decide

    d = decide("Summarise this report", [{"kind": "pdf_scanned", "name": "ir.pdf"}])
    assert d["needs_vision"] and d["chosen_role"] == "small_text" and d["perception"].startswith("OCR")


def test_escalation_blocked_when_large_model_missing(pinned, monkeypatch):
    from kila.router import cascade

    monkeypatch.setattr(cascade, "model_available", lambda role: (False, "qwen3:8b"))
    d = cascade.decide("something vague")
    assert not d["escalated"] and d["chosen_role"] == "small_text"
    assert "isn't available" in d["escalation_blocked"] and "escalation blocked" in d["summary"]


def test_classifier_unavailable_falls_back_honestly(pinned):
    from kila.router import cascade, classifier

    class Broken:
        name, device = "broken", "cpu"

        def raw(self, *a, **kw):
            raise classifier.ClassifierUnavailable("Laya checkpoint not found")

    classifier.set_classifier(Broken())
    d = cascade.decide("anything")
    assert d["ok"] is False and d["chosen_role"] == "small_text" and "unavailable" in d["summary"]


# ------------------------------------------------------------------ chat + API

def _sse(text):
    return [(b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1]))
            for b in text.strip().split("\n\n") if b.startswith("event:")]


def test_chat_auto_routes_and_records(pinned, client_for):
    eng = client_for("engineer")
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    evs = _sse(eng.post(f"/chat/sessions/{sid}/messages", json={"content": "something vague about E-2104"}).text)
    kinds = [k for k, _ in evs]
    assert kinds[:4] == ["status", "route", "start", "delta"] and kinds[-1] == "done"
    route = evs[1][1]
    assert route["escalated"] and route["chosen_model"] == "qwen3:8b" and route["task_id"]
    assert evs[2][1]["model"] == "qwen3:8b"  # the escalated model really answered
    assert "qwen3:8b" in "".join(d["text"] for k, d in evs if k == "delta")

    msgs = eng.get(f"/chat/sessions/{sid}/messages").json()
    assert msgs[1]["meta"]["route"]["task_id"] == route["task_id"]
    dec = eng.get("/router/decisions").json()[0]
    assert dec["task_id"] == route["task_id"] and dec["escalated"] and dec["status"] == "ok"
    ev = eng.get("/ledger/events?event_type=router.decision").json()[0]["payload"]
    assert ev["task_id"] == route["task_id"] and ev["chosen_model"] == "qwen3:8b"
    assert "vague" not in json.dumps(ev)  # the ledger never stores the request text
    call = eng.get("/ledger/events?event_type=llm.call").json()[0]["payload"]
    assert call["routed"] is True and call["task_id"] == route["task_id"]


def test_manual_role_skips_router(pinned, client_for):
    eng = client_for("engineer")
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    evs = _sse(eng.post(f"/chat/sessions/{sid}/messages", json={"content": "vague", "role": "small_text"}).text)
    assert "route" not in [k for k, _ in evs] and evs[0][1]["model"] == "qwen3.5:4b"
    assert eng.get("/router/decisions").json() == []


def test_router_api(pinned, client_for):
    eng = client_for("engineer")
    p = eng.post("/router/route", json={"text": "Calculate the corrosion rate", "retrieval_relevance": 0.9}).json()
    assert p["task_type"] == "engineering_calc" and p["retrieval_relevance"] == 0.9
    assert eng.get("/router/decisions").json() == []  # previews are not decisions
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    for text in ("What is the PSV interval?", "something vague", "Draft an approval note"):
        eng.post(f"/chat/sessions/{sid}/messages", json={"content": text})
    st = eng.get("/router/stats").json()
    assert st["decisions"] == 3 and st["escalated"] == 2 and st["escalation_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert st["by_model"] == {"qwen3.5:4b": 1, "qwen3:8b": 2}
    cfg = eng.get("/router/config").json()
    assert cfg["cascade"]["tau"] == 0.70 and cfg["classifier"]["name"] == "fake-keyword-classifier"
    assert eng.get("/router/calibration").status_code == 404  # tests use an empty metrics dir


def test_unknown_role_rejected(pinned, client_for):
    eng = client_for("engineer")
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    assert eng.post(f"/chat/sessions/{sid}/messages", json={"content": "x", "role": "wizard"}).status_code == 400

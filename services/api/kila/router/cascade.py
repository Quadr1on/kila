"""Confidence-calibrated cascade router (spec §6.3).

  score = alpha * task_conf + (1 - alpha) * retrieval_relevance     (task_conf alone without retrieval)
  role  = vision if the task needs vision, coder for code, else small_text
  escalate small_text -> large_text if score < tau, or difficulty is (confidently) high

Escalation only replaces the small text model: the coder and vision roles are specialists, so the
decision records that escalation was wanted but keeps them. If the large model isn't available on
this machine the decision says so ("escalation blocked") instead of pretending it escalated.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from sqlmodel import Session

from kila import ledger
from kila.db.models import RouterDecision, Task, utcnow
from kila.db.session import get_engine
from kila.models import health
from kila.models.registry import get_registry
from kila.router.classifier import ClassifierUnavailable, classify, config

log = logging.getLogger(__name__)
_avail_cache: dict[str, tuple[float, bool]] = {}
_avail_lock = threading.Lock()
AVAIL_TTL_S = 30.0


def model_available(role: str) -> tuple[bool, str]:
    """Is the model behind `role` downloaded on its server? Cached briefly; the router runs per message."""
    spec = get_registry().spec(role)
    key = f"{spec.backend.name}:{spec.name}"
    now = time.monotonic()
    with _avail_lock:
        hit = _avail_cache.get(key)
        if hit and now - hit[0] < AVAIL_TTL_S:
            return hit[1], spec.name
    st = health.backend_status(spec.backend)
    ok = bool(st.get("reachable")) and spec.name in st.get("pulled", {})
    with _avail_lock:
        _avail_cache[key] = (now, ok)
    return ok, spec.name


def clear_availability_cache() -> None:
    with _avail_lock:
        _avail_cache.clear()


def decide(user_text: str, attachments: list[dict[str, Any]] | None = None,
           retrieval_relevance: float | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    cfg = config()
    casc = cfg["cascade"]
    atts = attachments or []
    try:
        cls = classify(user_text, atts)
    except (ClassifierUnavailable, OSError) as e:
        # No classifier: route conservatively to the default model and say why.
        spec = get_registry().spec("small_text")
        return {"ok": False, "error": str(e), "task_type": None, "chosen_role": "small_text", "chosen_model": spec.name,
                "escalated": False, "summary": f"classifier unavailable → small_text ({spec.name})",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}

    tt, df, nv = cls["task_type"], cls["difficulty"], cls["needs_vision"]
    alpha, tau = float(casc["alpha"]), float(casc["tau"])

    # Vision: an attached scan/photo/drawing is decisive; otherwise trust a confident classifier "yes".
    vision_kinds = set(casc.get("vision_attachment_kinds", []))
    vision_from_attachment = any(a.get("kind") in vision_kinds for a in atts)
    vision_from_classifier = nv["choice"] == "A" and nv["conf"] >= casc.get("vision_min_conf", 0.6)
    needs_vision = vision_from_attachment or vision_from_classifier
    # Perception vs answering: an attached scan is already OCR'd (and vision-checked) at ingestion, so a
    # summary or approval note over it is a text task. The vision model answers only when the task is
    # about the picture itself: P&ID work, or the classifier confidently says vision is essential.
    vision_answers = tt["choice"] == "pid_digitise" or vision_from_classifier
    base_role = casc.get("role_by_task", {}).get(tt["choice"]) or ("vision" if vision_answers else "small_text")

    score = alpha * tt["conf"] + (1 - alpha) * retrieval_relevance if retrieval_relevance is not None else tt["conf"]
    reasons = []
    if score < tau:
        reasons.append(f"score {score:.2f} < τ {tau:.2f}")
    if casc.get("escalate_on_high_difficulty", True) and df["choice"] == "high" \
            and df["conf"] >= casc.get("high_difficulty_min_conf", 0.5):
        reasons.append(f"high difficulty ({df['conf']:.2f})")

    chosen, escalated, blocked = base_role, False, None
    if reasons and base_role == "small_text":
        ok, large = model_available("large_text")
        if ok:
            chosen, escalated = "large_text", True
        else:
            blocked = f"large_text model {large} isn't available on this machine"
    elif reasons:
        blocked = f"{base_role} is a specialist role; not replaced by large_text"

    spec = get_registry().spec(chosen)
    rel = f"{retrieval_relevance:.2f}" if retrieval_relevance is not None else "—"
    summary = (f"{tt['choice']} · conf {tt['conf']:.2f} · relevance {rel} · score {score:.2f} "
               f"{'<' if score < tau else '≥'} τ {tau:.2f} → {chosen}"
               + (" (escalated)" if escalated else "") + (f" · escalation blocked: {blocked}" if blocked else ""))
    return {
        "ok": True,
        "task_type": tt["choice"], "task_conf": tt["conf"],
        "difficulty": df["choice"], "difficulty_conf": df["conf"],
        "needs_vision": needs_vision,
        "vision_source": "attachment" if vision_from_attachment else "classifier" if vision_from_classifier else None,
        "perception": ("vision model answers" if base_role == "vision"
                       else "OCR + vision check at ingestion" if vision_from_attachment else None),
        "retrieval_relevance": retrieval_relevance,
        "alpha": alpha if retrieval_relevance is not None else 1.0, "tau": tau, "score": round(score, 4),
        "base_role": base_role, "chosen_role": chosen, "chosen_model": spec.name,
        "escalated": escalated, "escalation_reasons": reasons, "escalation_blocked": blocked,
        "classifier": cls["_meta"], "questions": {k: v for k, v in cls.items() if k != "_meta"},
        "summary": summary, "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def record(decision: dict[str, Any], *, session_id: str | None, actor: str, envelope: dict | None = None) -> str:
    """Persist as a Task + RouterDecision row and a ledger event. Returns the task id."""
    with Session(get_engine()) as s:
        task = Task(session_id=session_id, envelope_json=json.dumps(envelope or {}, default=str),
                    task_type=decision.get("task_type"), status="routed")
        s.add(task)
        s.commit()
        s.refresh(task)
        task_id = task.id
        if decision.get("ok"):
            s.add(RouterDecision(
                task_id=task_id, task_type=decision["task_type"], task_conf=decision["task_conf"],
                difficulty=decision["difficulty"], retrieval_relevance=decision["retrieval_relevance"] or 0.0,
                score=decision["score"], tau=decision["tau"], alpha=decision["alpha"],
                chosen_model=decision["chosen_model"], escalated=decision["escalated"],
                latency_ms=decision["latency_ms"]))
            s.commit()
    ledger.append(actor, "router.decision", {
        "task_id": task_id, "session_id": session_id,
        **{k: decision.get(k) for k in ("task_type", "task_conf", "difficulty", "needs_vision", "retrieval_relevance",
                                        "score", "alpha", "tau", "chosen_role", "chosen_model", "escalated",
                                        "escalation_blocked", "latency_ms")},
        "classifier_latency_ms": (decision.get("classifier") or {}).get("latency_ms"),
        "error": decision.get("error"),
    })
    return task_id


def finish(task_id: str, status: str) -> None:
    with Session(get_engine()) as s:
        t = s.get(Task, task_id)
        if t:
            t.status, t.finished_at = status, utcnow()
            s.add(t)
            s.commit()

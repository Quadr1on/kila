from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from kila import ledger
from kila.auth.deps import current_user
from kila.db.models import RouterDecision, Task, User
from kila.db.session import get_session
from kila.router import cascade, classifier
from kila.settings import get_settings

router = APIRouter(prefix="/router", tags=["router"])


class RouteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    attachment_kinds: list[str] = Field(default_factory=list, max_length=10)
    retrieval_relevance: float | None = Field(default=None, ge=0, le=1)


@router.post("/route")
async def preview(body: RouteIn, user: User = Depends(current_user)) -> dict[str, Any]:
    """Routing playground: what would the router do with this request? Nothing is answered or stored
    except a ledger entry (with a hash of the text, never the text)."""
    atts = [{"kind": k, "name": f"attachment.{k}"} for k in body.attachment_kinds]
    d = await run_in_threadpool(cascade.decide, body.text, atts, body.retrieval_relevance)
    ledger.append(user.name, "router.preview", {"text_sha256": hashlib.sha256(body.text.encode()).hexdigest(),
                                                "task_type": d.get("task_type"), "chosen_role": d.get("chosen_role"),
                                                "escalated": d.get("escalated")})
    return d


@router.get("/decisions")
def decisions(limit: int = Query(50, ge=1, le=500), _: User = Depends(current_user),
              session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.exec(select(RouterDecision, Task).join(Task, Task.id == RouterDecision.task_id)
                        .order_by(Task.created_at.desc()).limit(limit)).all()
    return [{"task_id": t.id, "created_at": t.created_at, "status": t.status, "task_type": d.task_type,
             "task_conf": d.task_conf, "difficulty": d.difficulty, "retrieval_relevance": d.retrieval_relevance,
             "score": d.score, "tau": d.tau, "alpha": d.alpha, "chosen_model": d.chosen_model, "escalated": d.escalated,
             "latency_ms": d.latency_ms} for d, t in rows]


@router.get("/stats")
def stats(_: User = Depends(current_user), session: Session = Depends(get_session)) -> dict[str, Any]:
    rows = session.exec(select(RouterDecision)).all()
    n = len(rows)
    lat = sorted(r.latency_ms for r in rows)
    return {
        "decisions": n,
        "escalated": sum(r.escalated for r in rows),
        "escalation_rate": round(sum(r.escalated for r in rows) / n, 4) if n else None,
        "below_tau": sum(r.score < r.tau for r in rows),
        "by_model": dict(Counter(r.chosen_model for r in rows)),
        "by_task_type": dict(Counter(r.task_type for r in rows)),
        "latency_ms": {"p50": lat[n // 2], "p95": lat[int(n * 0.95)], "mean": round(sum(lat) / n, 1)} if n else None,
    }


@router.get("/calibration")
def calibration(_: User = Depends(current_user)) -> dict[str, Any]:
    p = get_settings().metrics_dir / "router_calibration.json"
    if not p.exists():
        raise HTTPException(404, "not calibrated yet: run python -m kila.router.calibrate")
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/config")
def config(_: User = Depends(current_user)) -> dict[str, Any]:
    cfg = classifier.config()
    clf = classifier._clf
    return {"cascade": cfg["cascade"], "calibration": cfg.get("calibration", {}),
            "questions": {q: list(v["criteria"]) for q, v in cfg["questions"].items()},
            "classifier": {"loaded": clf is not None, "name": getattr(clf, "name", None),
                           "device": getattr(clf, "device", None), "load_ms": getattr(clf, "load_ms", None)}}

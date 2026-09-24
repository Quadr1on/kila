from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from kila.auth.deps import current_user, require_role
from kila.db.models import User
from kila.models import health
from kila.models.registry import ROLES, RegistryError, get_registry

router = APIRouter(prefix="/models", tags=["models"])


def _role_view(role: str, statuses: dict[str, dict[str, Any]], runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reg = get_registry()
    spec = reg.spec(role)
    st = statuses.get(spec.backend.name, {})
    cands = []
    for c in reg.candidates(role):
        cst = statuses.get(c["backend"], {})
        cands.append({"name": c["name"], "backend": c["backend"], "licence": c.get("licence"), "note": c.get("note"),
                      "pulled": c["name"] in cst.get("pulled", {}), "loaded": c["name"] in cst.get("loaded", {})})
    return {
        "role": role,
        "model": spec.name,
        "backend": spec.backend.name,
        "source": spec.source,
        "licence": spec.licence,
        "note": spec.note,
        "reachable": st.get("reachable", False),
        "pulled": spec.name in st.get("pulled", {}),
        "loaded": st.get("loaded", {}).get(spec.name),
        "warmup": runs.get(spec.name),
        "candidates": cands,
    }


@router.get("")
def overview(_: User = Depends(current_user)) -> dict[str, Any]:
    reg = get_registry()
    cfg = reg.config()
    try:
        backends = {name: reg.backend(name) for name in cfg["backends"]}
    except RegistryError as e:
        raise HTTPException(500, str(e)) from e
    used = {reg.spec(r).backend.name for r in ROLES} | {c["backend"] for r in ROLES for c in reg.candidates(r)}
    statuses = {n: health.backend_status(b) for n, b in backends.items() if n in used}
    runs = health.latest_runs()
    return {
        "profile": reg.profile,
        "profiles": list(cfg["profiles"]),
        "notes": cfg["profiles"][reg.profile].get("notes"),
        "gpu": health.gpu_info(),
        "backends": {n: {"base_url": backends[n].base_url, "kind": backends[n].kind,
                         "reachable": s.get("reachable"), "error": s.get("error"),
                         "loaded": s.get("loaded", {})} for n, s in statuses.items()},
        "roles": [_role_view(r, statuses, runs) for r in ROLES],
        "local_models": cfg.get("local_models", {}),
    }


@router.get("/roles")
def roles(_: User = Depends(current_user)) -> list[dict[str, Any]]:
    """Which model serves each role right now (no backend calls; cheap)."""
    reg = get_registry()
    return [{"role": r, "model": (s := reg.spec(r)).name, "backend": s.backend.name, "source": s.source}
            for r in ROLES]


class ActivateIn(BaseModel):
    name: str


@router.post("/{role}/activate")
def activate(role: str, body: ActivateIn, user: User = Depends(require_role("admin"))) -> dict[str, Any]:
    if role not in ROLES:
        raise HTTPException(404, f"unknown role {role}")
    try:
        spec = get_registry().activate(role, body.name, user.name)
    except RegistryError as e:
        raise HTTPException(400, str(e)) from e
    return {"role": role, "model": spec.name, "source": spec.source}


@router.post("/{role}/warmup")
async def warmup(role: str, user: User = Depends(require_role("engineer", "admin"))) -> dict[str, Any]:
    if role not in ROLES:
        raise HTTPException(404, f"unknown role {role}")
    spec = get_registry().spec(role)
    try:
        return await run_in_threadpool(health.warmup, spec, user.name)
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:300]
        raise HTTPException(502, f"{spec.backend.name} refused {spec.name}: {detail}") from e
    except httpx.HTTPError as e:
        raise HTTPException(503, f"can't reach {spec.backend.name} at {spec.backend.base_url}: {e}") from e

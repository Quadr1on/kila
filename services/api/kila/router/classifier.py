"""Laya task classifier, loaded from local checkpoints only, with per-question temperature calibration.

Gating uses the calibrated `answer_confidence` (max probability). Laya's docs are explicit that its
`confidence` field is a normalised-entropy score that is *not* calibrated and must not be compared
against thresholds; we still record it as `entropy_conf` for transparency.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import yaml

from kila.settings import REPO_ROOT, get_settings

log = logging.getLogger(__name__)


class ClassifierUnavailable(RuntimeError):
    pass


@lru_cache
def _load_cfg(path: Path, mtime: float) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def config() -> dict[str, Any]:
    p = get_settings().config_dir / "router.yaml"
    return _load_cfg(p, p.stat().st_mtime)


def apply_temperature(probs: dict[str, float], t: float) -> dict[str, float]:
    """Temperature-scale a probability vector: p_i^(1/T), renormalised (same as logits / T)."""
    if t == 1.0:
        return dict(probs)
    logs = {k: math.log(max(v, 1e-12)) / t for k, v in probs.items()}
    m = max(logs.values())
    ex = {k: math.exp(v - m) for k, v in logs.items()}
    z = sum(ex.values())
    return {k: v / z for k, v in ex.items()}


def build_state(user_text: str, attachments: list[dict[str, Any]] | None = None, max_chars: int = 1200) -> dict:
    """What the classifier sees: the request, plus a short summary of each attachment (spec §6.2)."""
    state: dict[str, Any] = {"message": user_text[:max_chars]}
    atts = attachments or []
    if atts:
        state["attachments"] = [{"kind": a.get("kind"), "name": a.get("name"),
                                 "excerpt": (a.get("excerpt") or "")[:300]} for a in atts]
    return state


class Classifier(Protocol):
    name: str
    device: str

    def raw(self, state: dict, questions: dict) -> dict[str, Any]: ...


class LayaClassifier:
    def __init__(self, cfg: dict):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        paths = {k: _local(cfg[k]) for k in ("english", "multilingual")}
        from laya import Router

        dev = cfg.get("device", "auto")
        if dev == "auto":
            import torch

            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = dev
        self.name = "laya"
        t0 = time.perf_counter()
        self._router = Router(models={k: str(v) for k, v in paths.items()}, device=dev, max_loaded=2)
        # Only the two checkpoints we ship. Router(preload=True) would also try typed-decisions,
        # which isn't downloaded: with HF_HUB_OFFLINE=1 that fails instead of going online.
        self._router.preload(["english", "multilingual"])
        self.load_ms = round((time.perf_counter() - t0) * 1000)
        self._lock = threading.Lock()

    def raw(self, state: dict, questions: dict) -> dict[str, Any]:
        with self._lock:
            out = self._router.predict(state, questions)
        return {"answers": out["answers"], "routing": out.get("routing", {})}


def _local(p: str) -> Path:
    path = Path(p) if Path(p).is_absolute() else REPO_ROOT / p
    if not (path / "rl_agent_config.json").exists():
        raise ClassifierUnavailable(f"Laya checkpoint not found at {path}. Run scripts/predownload.py --only hf --yes.")
    return path


_clf: Classifier | None = None
_lock = threading.Lock()
_warming: threading.Thread | None = None


def get_classifier() -> Classifier:
    global _clf
    with _lock:
        if _clf is None:
            _clf = LayaClassifier(config()["laya"])
            log.info("laya loaded on %s in %s ms", _clf.device, getattr(_clf, "load_ms", "?"))
        return _clf


def set_classifier(c: Classifier | None) -> None:
    global _clf
    _clf = c


def warm_in_background() -> None:
    """Load Laya off the request path so the first routed message isn't a 15 s cold start."""
    global _warming
    if _clf is not None or (_warming and _warming.is_alive()):
        return

    def run():
        try:
            get_classifier()
        except Exception as e:  # missing checkpoint: routing will report it per request
            log.warning("laya warm-up skipped: %s", e)

    _warming = threading.Thread(target=run, name="laya-warm", daemon=True)
    _warming.start()


def classify(user_text: str, attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Run Laya, calibrate each question, return a compact, JSON-safe result."""
    cfg = config()
    clf = get_classifier()
    state = build_state(user_text, attachments, cfg["laya"].get("state_chars", 1200))
    t0 = time.perf_counter()
    out = clf.raw(state, cfg["questions"])
    ms = round((time.perf_counter() - t0) * 1000, 1)
    temps = cfg.get("calibration", {})
    result: dict[str, Any] = {}
    for q, a in out["answers"].items():
        raw = {k: float(v) for k, v in a["probabilities"].items()}
        cal = apply_temperature(raw, float(temps.get(q, 1.0)))
        choice = max(cal, key=cal.get)
        result[q] = {"choice": choice, "conf": round(cal[choice], 4), "raw_choice": a.get("choice"),
                     "raw_conf": round(max(raw.values()), 4), "entropy_conf": round(float(a.get("confidence", 0)), 4),
                     "probs": {k: round(v, 4) for k, v in cal.items()}}
    routing = out.get("routing") or {}
    result["_meta"] = {"classifier": clf.name, "checkpoint": routing.get("model"), "device": clf.device,
                       "language": (routing.get("detection") or {}).get("language"), "latency_ms": ms}
    return result

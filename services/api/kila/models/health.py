"""Backend health, GPU/VRAM facts and measured warm-up (tokens/sec, load = swap time).

Numbers here are measured, never assumed: Ollama reports load/prompt/eval durations in ns for
every generate call, and /api/ps reports what is resident and how much of it sits in VRAM.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from kila import ledger
from kila.models.registry import Backend, ModelSpec
from kila.settings import get_settings

WARMUP_PROMPT = "In one short sentence, say what a pressure safety valve does."
WARMUP_TOKENS = 64
_TIMEOUT = httpx.Timeout(5.0, read=600.0)


def gpu_info() -> dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"available": False, "reason": "nvidia-smi not found in this environment"}
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.used,memory.total,driver_version,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.SubprocessError, OSError) as e:
        return {"available": False, "reason": str(e)}
    gpus = []
    for line in out:
        name, used, total, driver, util = [x.strip() for x in line.split(",")]
        gpus.append({"name": name, "vram_used_mib": int(used), "vram_total_mib": int(total),
                     "driver": driver, "utilization_pct": int(util)})
    return {"available": True, "gpus": gpus}


def backend_status(b: Backend) -> dict[str, Any]:
    """Which models the server has on disk and which are resident right now."""
    try:
        with httpx.Client(timeout=3.0) as c:
            if b.kind == "ollama":
                tags = c.get(f"{b.base_url}/api/tags").raise_for_status().json()
                ps = c.get(f"{b.base_url}/api/ps").raise_for_status().json()
                return {
                    "reachable": True,
                    "pulled": {m["name"]: {"size": m.get("size")} for m in tags.get("models", [])},
                    "loaded": {m["name"]: {"size": m.get("size"), "size_vram": m.get("size_vram"),
                                           "expires_at": m.get("expires_at"),
                                           "context_length": m.get("context_length")}
                               for m in ps.get("models", [])},
                }
            models = c.get(f"{b.openai_base}/models").raise_for_status().json()
            names = {m["id"]: {} for m in models.get("data", [])}
            return {"reachable": True, "pulled": names, "loaded": names}
    except (httpx.HTTPError, ValueError) as e:
        return {"reachable": False, "error": f"{type(e).__name__}: {e}", "pulled": {}, "loaded": {}}


def _ollama_warmup(spec: ModelSpec) -> dict[str, Any]:
    b = spec.backend
    before = backend_status(b)["loaded"]
    body = {"model": spec.name, "prompt": WARMUP_PROMPT, "stream": False, "think": False,
            "keep_alive": spec.params.get("keep_alive", "10m"), "options": {"num_predict": WARMUP_TOKENS}}
    t0 = time.perf_counter()
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.post(f"{b.base_url}/api/generate", json=body)
        r.raise_for_status()
        d = r.json()
    wall_ms = (time.perf_counter() - t0) * 1000
    after = backend_status(b)["loaded"].get(spec.name, {})
    ns = 1e-9
    eval_s = d.get("eval_duration", 0) * ns
    prompt_s = d.get("prompt_eval_duration", 0) * ns
    return {
        "was_resident": spec.name in before,
        "evicted": sorted(set(before) - {spec.name} - set(backend_status(b)["loaded"])),
        "load_ms": round(d.get("load_duration", 0) * ns * 1000, 1),
        "prompt_tokens": d.get("prompt_eval_count"),
        "prompt_tok_s": round(d.get("prompt_eval_count", 0) / prompt_s, 1) if prompt_s else None,
        "completion_tokens": d.get("eval_count"),
        "tok_s": round(d.get("eval_count", 0) / eval_s, 1) if eval_s else None,
        "total_ms": round(d.get("total_duration", 0) * ns * 1000, 1),
        "wall_ms": round(wall_ms, 1),
        "size_vram": after.get("size_vram"),
        "size": after.get("size"),
    }


def _openai_warmup(spec: ModelSpec) -> dict[str, Any]:
    b = spec.backend
    body = {"model": spec.name, "stream": True, "max_tokens": WARMUP_TOKENS,
            "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": WARMUP_PROMPT}]}
    t0 = time.perf_counter()
    first = None
    usage: dict[str, Any] = {}
    with httpx.Client(timeout=_TIMEOUT) as c, c.stream("POST", f"{b.openai_base}/chat/completions", json=body) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            if first is None and chunk.get("choices") and chunk["choices"][0]["delta"].get("content"):
                first = time.perf_counter()
            usage = chunk.get("usage") or usage
    end = time.perf_counter()
    n = usage.get("completion_tokens") or 0
    gen_s = end - (first or end)
    return {"was_resident": None, "load_ms": None, "ttft_ms": round(((first or end) - t0) * 1000, 1),
            "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": n,
            "tok_s": round(n / gen_s, 1) if gen_s > 0 else None, "wall_ms": round((end - t0) * 1000, 1)}


def warmup(spec: ModelSpec, actor: str) -> dict[str, Any]:
    result = _ollama_warmup(spec) if spec.backend.kind == "ollama" else _openai_warmup(spec)
    run = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "role": spec.role,
           "model": spec.name, "backend": spec.backend.name, **result}
    _record(run)
    ledger.append(actor, "model.warmup", {k: run[k] for k in ("role", "model", "backend", "tok_s", "load_ms",
                                                               "was_resident", "wall_ms")})
    return run


# ------------------------------------------------------------ metrics file

def _metrics_path():
    d = get_settings().metrics_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / "model_warmup.json"


def _record(run: dict[str, Any], keep: int = 500) -> None:
    p = _metrics_path()
    runs = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    runs.append(run)
    p.write_text(json.dumps(runs[-keep:], indent=1), encoding="utf-8")


def latest_runs() -> dict[str, dict[str, Any]]:
    """Most recent warm-up per model, plus its most recent *cold* load (= measured swap time)."""
    p = _metrics_path()
    if not p.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for run in json.loads(p.read_text(encoding="utf-8")):
        prev = out.get(run["model"], {})
        cold = run if run.get("was_resident") is False else prev.get("last_cold")
        out[run["model"]] = {**run, "last_cold": cold and {k: cold.get(k) for k in ("ts", "load_ms", "evicted")}}
    return out

"""Calibrate the Laya classifier on seed/router_labels.jsonl and tune tau.

    uv run --directory services/api python -m kila.router.calibrate [--refresh] [--target 0.95]

1. Run Laya once per labelled request (cached in metrics/router_raw_probs.jsonl; --refresh re-runs).
2. 5-fold cross-validation, stratified by task type: every request is scored with a temperature
   fitted WITHOUT it, so all labels contribute out-of-fold (OOF) before/after numbers.
   (A single 70/30 split left 88 test rows and the fitted temperature overfit it.)
3. Per question: the final temperature is fitted on all labels by minimising NLL, and applied
   only if cross-validation shows it lowers out-of-fold NLL; otherwise T stays 1.0.
4. Report OOF accuracy, ECE and NLL before/after, and task-type accuracy per language.
5. Sweep tau on the OOF-calibrated probabilities: escalation rate vs task-type accuracy of the
   requests kept on the small model; pick the smallest-escalation tau with kept accuracy >= --target.
Writes the temperatures and tau into config/router.yaml and everything into metrics/router_calibration.json.

alpha is NOT tuned here: it weighs classifier confidence against retrieval relevance, and the
labelled set has no retrieval. It is tuned on the Phase 8 golden set (spec §8).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from kila.router.classifier import apply_temperature, build_state, config, get_classifier
from kila.settings import REPO_ROOT, get_settings

QUESTIONS = ("task_type", "difficulty", "needs_vision")
BINS = 15


def gold(row: dict, q: str) -> str:
    if q == "needs_vision":
        return "A" if row["needs_vision"] else "B"
    return row[q]


def ece(confs: list[float], correct: list[bool], bins: int = BINS) -> float:
    if not confs:
        return float("nan")
    total, e = len(confs), 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, c in enumerate(confs) if (c >= lo if i == 0 else c > lo) and c <= hi]
        if idx:
            e += len(idx) / total * abs(sum(confs[j] for j in idx) / len(idx) - sum(correct[j] for j in idx) / len(idx))
    return round(e, 4)


def nll(rows: list[dict], q: str, t: float) -> float:
    s = 0.0
    for r in rows:
        p = apply_temperature(r["probs"][q], t)
        s -= math.log(max(p.get(gold(r, q), 0.0), 1e-12))
    return s / max(len(rows), 1)


def fit_temperature(rows: list[dict], q: str) -> float:
    grid = [round(0.5 + 0.05 * i, 2) for i in range(191)]  # 0.5 .. 10.0
    return min(grid, key=lambda t: nll(rows, q, t))


def evaluate(rows: list[dict], q: str, t: float) -> dict[str, Any]:
    confs, correct = [], []
    for r in rows:
        p = apply_temperature(r["probs"][q], t)
        choice = max(p, key=p.get)
        confs.append(p[choice])
        correct.append(choice == gold(r, q))
    return {"n": len(rows), "accuracy": round(sum(correct) / len(rows), 4), "ece": ece(confs, correct),
            "mean_conf": round(sum(confs) / len(confs), 4), "nll": round(nll(rows, q, t), 4)}


def folds(rows: list[dict], k: int = 5, seed: int = 13) -> list[int]:
    """Stratified fold id per row (by task type), deterministic."""
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["task_type"]].append(i)
    rng = random.Random(seed)
    fold = [0] * len(rows)
    for idx in by.values():
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            fold[i] = j % k
    return fold


def evaluate_rowwise(rows: list[dict], q: str) -> dict[str, Any]:
    """Like evaluate(), but each row uses its own out-of-fold temperature r['T'][q]."""
    confs, correct, nl = [], [], 0.0
    for r in rows:
        p = apply_temperature(r["probs"][q], r["T"][q])
        choice = max(p, key=p.get)
        confs.append(p[choice])
        correct.append(choice == gold(r, q))
        nl -= math.log(max(p.get(gold(r, q), 0.0), 1e-12))
    return {"n": len(rows), "accuracy": round(sum(correct) / len(rows), 4), "ece": ece(confs, correct),
            "mean_conf": round(sum(confs) / len(confs), 4), "nll": round(nl / len(rows), 4)}


def escalates(r: dict, tau: float, casc: dict) -> bool:
    """The cascade's decision with no retrieval (score = task confidence), using the row's OOF temperatures."""
    temps = r["T"]
    tt = apply_temperature(r["probs"]["task_type"], temps["task_type"])
    score = max(tt.values())
    diff = apply_temperature(r["probs"]["difficulty"], temps["difficulty"])
    high = max(diff, key=diff.get) == "high" and diff["high"] >= casc["high_difficulty_min_conf"]
    return score < tau or (casc.get("escalate_on_high_difficulty", True) and high)


def sweep(rows: list[dict], casc: dict) -> list[dict]:
    out = []
    for i in range(0, 20):
        tau = round(0.05 * i, 2)
        kept = [r for r in rows if not escalates(r, tau, casc)]
        esc = len(rows) - len(kept)

        def right(r):
            p = apply_temperature(r["probs"]["task_type"], r["T"]["task_type"])
            return max(p, key=p.get) == r["task_type"]

        gold_high = [r for r in rows if r["difficulty"] == "high"]
        out.append({"tau": tau, "escalation_rate": round(esc / len(rows), 4),
                    "kept_accuracy": round(sum(map(right, kept)) / len(kept), 4) if kept else None,
                    "hard_escalated": round(sum(escalates(r, tau, casc) for r in gold_high) / len(gold_high), 4)
                    if gold_high else None})
    return out


def pick_tau(points: list[dict], target: float) -> float:
    ok = [p for p in points if p["kept_accuracy"] is not None and p["kept_accuracy"] >= target]
    return min(ok, key=lambda p: (p["escalation_rate"], p["tau"]))["tau"] if ok else max(p["tau"] for p in points)


# ------------------------------------------------------------------ running Laya over the labels

def _key(row: dict) -> str:
    return hashlib.sha256(json.dumps([row["text"], row["attachments"]], ensure_ascii=False).encode()).hexdigest()[:16]


def collect(labels: list[dict], refresh: bool) -> list[dict]:
    cache_p = get_settings().metrics_dir / "router_raw_probs.jsonl"
    cache = {}
    if cache_p.exists() and not refresh:
        for line in cache_p.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            cache[d["key"]] = d
    clf = get_classifier()
    cfg = config()
    out, new = [], 0
    for i, row in enumerate(labels):
        k = _key(row)
        if k not in cache:
            atts = [{"kind": kind, "name": f"attachment.{kind}"} for kind in row["attachments"]]
            import time

            t0 = time.perf_counter()
            res = clf.raw(build_state(row["text"], atts), cfg["questions"])
            ms = (time.perf_counter() - t0) * 1000
            cache[k] = {"key": k, "latency_ms": round(ms, 1), "checkpoint": res["routing"].get("model"),
                        "probs": {q: {c: float(p) for c, p in res["answers"][q]["probabilities"].items()} for q in QUESTIONS},
                        "entropy_conf": {q: float(res["answers"][q].get("confidence", 0)) for q in QUESTIONS}}
            new += 1
            if new % 25 == 0:
                print(f"  classified {i + 1}/{len(labels)}", flush=True)
        out.append({**row, **cache[k]})
    cache_p.parent.mkdir(parents=True, exist_ok=True)
    cache_p.write_text("\n".join(json.dumps(v, ensure_ascii=False) for v in cache.values()) + "\n", encoding="utf-8")
    return out


def write_config(temps: dict[str, float], tau: float) -> None:
    p = get_settings().config_dir / "router.yaml"
    s = p.read_text(encoding="utf-8")
    for q, t in temps.items():
        s = re.sub(rf"(^  {q}: )[0-9.]+", rf"\g<1>{t}", s, count=1, flags=re.M)
    s = re.sub(r"(^  tau: )[0-9.]+", rf"\g<1>{tau}", s, count=1, flags=re.M)
    p.write_text(s, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-run Laya on every label (ignore the cache)")
    ap.add_argument("--target", type=float, default=0.95, help="min task-type accuracy on requests kept on small_text")
    ap.add_argument("--no-write", action="store_true", help="report only; don't update config/router.yaml")
    args = ap.parse_args()

    labels = [json.loads(line) for line in (REPO_ROOT / "seed" / "router_labels.jsonl").read_text("utf-8").splitlines() if line]
    print(f"{len(labels)} labelled requests; running Laya (cached results reused)...", flush=True)
    rows = collect(labels, args.refresh)
    fold = folds(rows)
    k = max(fold) + 1
    casc = config()["cascade"]

    report: dict[str, Any] = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              "labels": len(rows), "method": f"{k}-fold cross-validation (stratified by task type)",
                              "questions": {}}
    for r in rows:
        r["T"] = {}
    temps: dict[str, float] = {}
    for q in QUESTIONS:
        fold_t = [fit_temperature([r for r, f in zip(rows, fold) if f != i], q) for i in range(k)]
        for r, f in zip(rows, fold):
            r["T"][q] = fold_t[f]
        before, after = evaluate(rows, q, 1.0), evaluate_rowwise(rows, q)
        t_all = fit_temperature(rows, q)
        helps = after["nll"] < before["nll"]
        temps[q] = t_all if helps else 1.0
        if not helps:  # CV says scaling doesn't generalise: keep raw probabilities for this question
            for r in rows:
                r["T"][q] = 1.0
            after = evaluate_rowwise(rows, q)
        ent_conf = [r["entropy_conf"][q] for r in rows]
        ent_right = [max(r["probs"][q], key=r["probs"][q].get) == gold(r, q) for r in rows]
        report["questions"][q] = {"temperature": temps[q], "fitted_temperature": t_all, "applied": helps,
                                  "fold_temperatures": fold_t, "before": before, "after": after,
                                  "laya_entropy_conf_ece": ece(ent_conf, ent_right)}
        print(f"{q:13} T={temps[q]:<5} ({'applied' if helps else 'NOT applied: no CV gain'}; folds {fold_t})"
              f" acc {before['accuracy']:.3f} | ECE {before['ece']:.3f} -> {after['ece']:.3f}"
              f" | NLL {before['nll']:.3f} -> {after['nll']:.3f}", flush=True)

    per_lang = defaultdict(lambda: [0, 0])
    confusion = Counter()
    for r in rows:
        p = apply_temperature(r["probs"]["task_type"], r["T"]["task_type"])
        c = max(p, key=p.get)
        per_lang[r["lang"]][0] += c == r["task_type"]
        per_lang[r["lang"]][1] += 1
        if c != r["task_type"]:
            confusion[f"{r['task_type']} -> {c}"] += 1
    report["task_type_accuracy_by_language"] = {kk: {"accuracy": round(a_ / n, 4), "n": n} for kk, (a_, n) in per_lang.items()}
    report["task_type_top_confusions"] = confusion.most_common(8)

    points = sweep(rows, casc)
    tau = pick_tau(points, args.target)
    chosen = next(pt for pt in points if pt["tau"] == tau)
    report["tau_sweep"] = {"target_kept_accuracy": args.target, "chosen_tau": tau, "test": points, "chosen_on_test": chosen,
                           "note": "out-of-fold probabilities; tau itself is chosen on the same curve (one scalar)"}
    report["alpha"] = {"value": casc["alpha"], "tuned": False,
                       "note": "needs retrieval relevance per request; tuned on the Phase 8 golden set"}
    lat = sorted(r["latency_ms"] for r in rows)
    by_ckpt = defaultdict(list)
    for r in rows:
        by_ckpt[r["checkpoint"]].append(r["latency_ms"])
    report["laya_latency_ms"] = {"device": get_classifier().device, "p50": lat[len(lat) // 2], "p95": lat[int(len(lat) * 0.95)],
                                 "by_checkpoint_p50": {k: sorted(v)[len(v) // 2] for k, v in by_ckpt.items()}}
    print(f"tau={tau}: escalation {chosen['escalation_rate']:.1%}, kept accuracy {chosen['kept_accuracy']}, "
          f"hard tasks escalated {chosen['hard_escalated']} (out-of-fold)")
    print("task_type accuracy by language:", dict(report["task_type_accuracy_by_language"]))
    print("laya latency:", report["laya_latency_ms"])

    dest = get_settings().metrics_dir / "router_calibration.json"
    dest.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if not args.no_write:
        write_config(temps, tau)
        print("updated config/router.yaml (calibration temperatures, tau)")
    print("written:", dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

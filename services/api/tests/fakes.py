"""Tiny deterministic stand-ins for bge-m3 and bge-reranker (tests must not load 2 GB models)."""

from __future__ import annotations

import hashlib
import math

from kila.rag.bm25 import tokenize


class HashEmbedder:
    """Bag-of-words hashed into 256 dims, L2-normalised: similar words -> similar vectors."""

    name, device, dim = "fake-hash-embedder", "cpu", 256

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in tokenize(t):
                v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class OverlapReranker:
    """Relevance = fraction of query tokens present in the passage."""

    name, device, top_n = "fake-overlap-reranker", "cpu", 30

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(tokenize(query))
        return [len(q & set(tokenize(p))) / max(len(q), 1) for p in passages]


class KeywordClassifier:
    """Stands in for Laya: keyword -> task type, fixed probabilities, deterministic."""

    name, device = "fake-keyword-classifier", "cpu"
    RULES = [("approval", "approval_note"), ("p&id", "pid_digitise"), ("drawing", "pid_digitise"),
             ("calculate", "engineering_calc"), ("code", "code_task"), ("python", "code_task"),
             ("email", "correspondence"), ("letter", "correspondence"), ("spreadsheet", "sheet_analysis"),
             ("summar", "inspection_summary")]
    TASKS = ["approval_note", "inspection_summary", "engineering_calc", "pid_digitise", "code_task",
             "correspondence", "sheet_analysis", "general_qa"]

    def raw(self, state: dict, questions: dict) -> dict:
        text = state["message"].lower()
        task = next((t for k, t in self.RULES if k in text), "general_qa")
        unsure = "vague" in text
        top = 0.30 if unsure else 0.90
        rest = (1 - top) / (len(self.TASKS) - 1)
        tt = {t: (top if t == task else rest) for t in self.TASKS}
        hard = "urgent" in text or task == "approval_note"
        diff = {"low": 0.1, "medium": 0.2, "high": 0.7} if hard else {"low": 0.7, "medium": 0.2, "high": 0.1}
        vis = {"A": 0.8, "B": 0.2} if task == "pid_digitise" else {"A": 0.1, "B": 0.9}

        def ans(p):
            c = max(p, key=p.get)
            return {"type": "choice", "choice": c, "probabilities": p, "confidence": 0.5, "answer_confidence": p[c]}

        return {"answers": {"task_type": ans(tt), "difficulty": ans(diff), "needs_vision": ans(vis)},
                "routing": {"model": "english", "detection": {"language": "en"}}}

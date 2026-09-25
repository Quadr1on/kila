"""Retrieval for grounded chat answers: pick sources, format them for the prompt, check citations."""

from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from kila.db.models import KBDocument
from kila.db.session import get_engine
from kila.rag import service
from kila.settings import get_settings

_CITE = re.compile(r"\[S(\d+)\]")


class NotReady(Exception):
    """An attachment hasn't finished extraction/indexing yet."""


def check_attachments_ready(object_ids: list[str]) -> None:
    with Session(get_engine()) as s:
        docs = {d.object_id: d for d in s.exec(select(KBDocument).where(KBDocument.object_id.in_(object_ids))).all()}
    for oid in object_ids:
        d = docs.get(oid)
        if d is None:
            raise NotReady(f"attachment {oid} hasn't been read yet; index it first")
        if d.status == "error":
            raise NotReady(f"attachment {d.title}: {d.error}")
        if d.status != "indexed":
            raise NotReady(f"attachment {d.title} is still being read ({d.status})")


def retrieve(question: str, attachments: list[str], use_kb: bool) -> dict[str, Any]:
    cfg = service.config()["answering"]
    results: list[dict[str, Any]] = []
    relevance = []
    timings = {}
    if attachments:
        r = service.search(question, object_ids=attachments, final_k=cfg["attachment_chunks"])
        results += r["results"]
        relevance.append(r["retrieval_relevance"])
        timings["attachments_ms"] = r["timings_ms"]["total_ms"]
    if use_kb:
        r = service.search(question)
        seen = {x["chunk_id"] for x in results}
        results += [x for x in r["results"] if x["chunk_id"] not in seen]
        relevance.append(r["retrieval_relevance"])
        timings["kb_ms"] = r["timings_ms"]["total_ms"]
    # Keep the best-scoring passages within the prompt budget, then number them in that order.
    results.sort(key=lambda x: x["score"], reverse=True)
    picked, used = [], 0
    for x in results:
        if used + len(x["text"]) > cfg["max_context_chars"] and picked:
            break
        picked.append(x)
        used += len(x["text"])
    sources = [{"n": i + 1, "chunk_id": x["chunk_id"], "object_id": x["object_id"], "name": x["name"],
                "title": x["title"], "page": x["page"], "char_start": x["char_start"], "char_end": x["char_end"],
                "score": x["score"], "text": x["text"]} for i, x in enumerate(picked)]
    rel = [v for v in relevance if v is not None]
    return {"sources": sources, "retrieval_relevance": max(rel) if rel else None, "timings_ms": timings}


def grounded_prompt() -> str:
    return (get_settings().config_dir / "prompts" / "grounded_answer.md").read_text(encoding="utf-8").strip()


def format_question(question: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return f"No sources were found for this question.\n\nQuestion: {question}"
    blocks = [f"[S{s['n']}] {s['name']}, page {s['page']}:\n{s['text']}" for s in sources]
    return "Sources:\n\n" + "\n\n".join(blocks) + f"\n\nQuestion: {question}"


def check_citations(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    cited = sorted({int(n) for n in _CITE.findall(answer)})
    valid = {s["n"] for s in sources}
    return {"cited": [n for n in cited if n in valid], "invalid": [n for n in cited if n not in valid],
            "uncited_answer": bool(sources) and not cited}

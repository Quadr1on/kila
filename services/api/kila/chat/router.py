"""Phase 1 chat: streaming replies from the `small_text` role over SSE.

Full message text lives in the `messages` table; the ledger gets hashes, token counts and timings.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from kila import ledger
from kila.auth.deps import current_user
from kila.db.models import ChatSession, Message, User, utcnow
from kila.db.session import get_engine, get_session
from kila.ledger.chain import canonical_json
from kila.models.registry import ROLES, get_registry
from kila.rag import answer
from kila.storage import store
from kila.storage.store import StorageError
from kila.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])
HISTORY_TURNS = 20
HEARTBEAT_S = 10.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _system_prompt() -> str:
    return (get_settings().config_dir / "prompts" / "general_chat.md").read_text(encoding="utf-8").strip()


def _own_session(session: Session, session_id: str, user: User) -> ChatSession:
    cs = session.get(ChatSession, session_id)
    if cs is None or (cs.user_id != user.id and user.role != "admin"):
        raise HTTPException(404, "chat not found")
    return cs


def _msg_out(m: Message) -> dict[str, Any]:
    return {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at,
            "meta": json.loads(m.meta_json or "{}")}


# ------------------------------------------------------------ sessions

class SessionIn(BaseModel):
    title: str = ""


@router.get("/sessions")
def list_sessions(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(select(ChatSession).where(ChatSession.user_id == user.id)
                        .order_by(ChatSession.created_at.desc()).limit(100)).all()
    return [{"id": r.id, "title": r.title or "Untitled", "created_at": r.created_at} for r in rows]


@router.post("/sessions")
def create_session(body: SessionIn, user: User = Depends(current_user),
                   session: Session = Depends(get_session)) -> dict:
    cs = ChatSession(user_id=user.id, title=body.title[:120])
    session.add(cs)
    session.commit()
    session.refresh(cs)
    return {"id": cs.id, "title": cs.title or "Untitled", "created_at": cs.created_at}


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str, user: User = Depends(current_user),
                  session: Session = Depends(get_session)) -> list[dict]:
    _own_session(session, session_id, user)
    rows = session.exec(select(Message).where(Message.session_id == session_id).order_by(Message.id)).all()
    return [_msg_out(m) for m in rows]


# ------------------------------------------------------------ streaming reply

class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    role: str = "small_text"
    # Phase 2: grounding. Attachments must already be read + indexed (POST /kb/documents/{id}/index).
    attachments: list[str] = Field(default_factory=list, max_length=10)
    use_kb: bool = False


async def _with_heartbeat(agen: AsyncIterator[Any], every_s: float) -> AsyncIterator[Any]:
    """Yield items from `agen`; yield None whenever it has been silent for `every_s` seconds."""
    it = agen.__aiter__()
    nxt = asyncio.ensure_future(it.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({nxt}, timeout=every_s)
            if not done:
                yield None
                continue
            try:
                item = nxt.result()
            except StopAsyncIteration:
                return
            yield item
            nxt = asyncio.ensure_future(it.__anext__())
    finally:
        nxt.cancel()


def _rag_cfg() -> dict[str, Any]:
    from kila.rag.service import config

    return config()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageIn, user: User = Depends(current_user),
                       session: Session = Depends(get_session)) -> StreamingResponse:
    if body.role not in ROLES:
        raise HTTPException(400, f"unknown role {body.role}")
    cs = _own_session(session, session_id, user)
    grounded = bool(body.attachments) or body.use_kb
    attach_names: dict[str, str] = {}
    for oid in body.attachments:
        try:
            obj = store.get_object(session, oid)
            store.check_access(user, store.bucket_name_of(session, obj), "read")
            attach_names[oid] = obj.original_name
        except StorageError as e:
            raise HTTPException(e.status, e.detail) from e
    if body.attachments:
        try:
            answer.check_attachments_ready(body.attachments)
        except answer.NotReady as e:
            raise HTTPException(409, str(e)) from e
    if not cs.title:
        cs.title = body.content.strip().splitlines()[0][:80]
        session.add(cs)
    user_meta = {"attachments": [{"object_id": k, "name": v} for k, v in attach_names.items()],
                 "use_kb": body.use_kb} if grounded else {}
    session.add(Message(session_id=session_id, role="user", content=body.content, meta_json=json.dumps(user_meta)))
    session.commit()

    history = session.exec(select(Message).where(Message.session_id == session_id)
                           .order_by(Message.id.desc()).limit(HISTORY_TURNS)).all()[::-1]
    system = _system_prompt() + (f"\n\n{answer.grounded_prompt()}" if grounded else "")
    messages = [{"role": "system", "content": system}] + [
        {"role": m.role, "content": m.content} for m in history if m.content
    ]
    spec = get_registry().spec(body.role)
    # Grounded answers should copy from sources, not improvise: use the configured low temperature.
    llm = get_registry().get_llm(body.role, **({"temperature": _rag_cfg()["answering"]["temperature"]} if grounded else {}))

    async def stream() -> AsyncIterator[str]:
        yield _sse("start", {"role": spec.role, "model": spec.name, "backend": spec.backend.name,
                             "source": spec.source})
        grounding: dict[str, Any] | None = None
        if grounded:
            yield _sse("status", {"stage": "retrieving"})
            try:
                found = await run_in_threadpool(answer.retrieve, body.content, body.attachments, body.use_kb)
            except Exception as e:  # embedder/reranker missing etc.: say so, answer nothing
                yield _sse("error", {"detail": f"Couldn't search the documents: {type(e).__name__}: {e}"[:400]})
                return
            grounding = {"sources": found["sources"], "retrieval_relevance": found["retrieval_relevance"],
                         "retrieval_ms": found["timings_ms"]}
            messages[-1] = {"role": "user", "content": answer.format_question(body.content, found["sources"])}
            yield _sse("sources", {"sources": [_public_source(x) for x in found["sources"]],
                                   "retrieval_relevance": found["retrieval_relevance"]})
        parts: list[str] = []
        usage: dict[str, Any] = {}
        t0 = time.perf_counter()
        t_first: float | None = None
        status, error = "ok", None
        try:
            async for chunk in _with_heartbeat(llm.astream(messages), HEARTBEAT_S):
                if chunk is None:
                    yield ": keep-alive\n\n"  # SSE comment; keeps proxies from timing out a cold load
                    continue
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    if t_first is None:
                        t_first = time.perf_counter()
                    parts.append(text)
                    yield _sse("delta", {"text": text})
                if getattr(chunk, "usage_metadata", None):
                    usage = dict(chunk.usage_metadata)
        except asyncio.CancelledError:
            status = "aborted"  # client pressed Stop or went away; keep what we have
            raise
        except Exception as e:  # backend down, model missing, ...
            status, error = "error", f"{type(e).__name__}: {e}"[:500]
            yield _sse("error", {"detail": _friendly(error, spec.name, spec.backend.base_url)})
        finally:
            meta = _finish(session_id, user, spec, messages, "".join(parts), usage, t0, t_first, status, error,
                           grounding)
        if status == "ok":
            yield _sse("done", meta)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


def _public_source(x: dict[str, Any]) -> dict[str, Any]:
    return {k: x[k] for k in ("n", "chunk_id", "object_id", "name", "title", "page", "score")} | {
        "snippet": x["text"][:600]}


def _finish(session_id: str, user: User, spec, messages: list[dict], reply: str, usage: dict[str, Any],
            t0: float, t_first: float | None, status: str, error: str | None,
            grounding: dict[str, Any] | None = None) -> dict[str, Any]:
    end = time.perf_counter()
    out_tokens = usage.get("output_tokens")
    gen_s = end - t_first if t_first else 0
    meta = {
        "role": spec.role, "model": spec.name, "backend": spec.backend.name, "status": status,
        "input_tokens": usage.get("input_tokens"), "output_tokens": out_tokens,
        "ttft_ms": round((t_first - t0) * 1000, 1) if t_first else None,
        "latency_ms": round((end - t0) * 1000, 1),
        "tok_s": round(out_tokens / gen_s, 1) if out_tokens and gen_s > 0 else None,
    }
    if grounding is not None:
        cites = answer.check_citations(reply, grounding["sources"])
        meta["grounding"] = {"sources": [_public_source(x) for x in grounding["sources"]],
                             "retrieval_relevance": grounding["retrieval_relevance"],
                             "retrieval_ms": grounding["retrieval_ms"], **cites}
    with Session(get_engine()) as s:
        msg = Message(session_id=session_id, role="assistant", content=reply, meta_json="{}", created_at=utcnow())
        if reply or status == "ok":
            s.add(msg)
            s.commit()
            s.refresh(msg)
            meta["message_id"] = msg.id
    ev = ledger.append(user.name, "llm.call" if status != "error" else "llm.call_failed", {
        **{k: meta[k] for k in ("role", "model", "backend", "status", "input_tokens", "output_tokens",
                                "ttft_ms", "latency_ms")},
        "session_id": session_id,
        "prompt_sha256": _sha(canonical_json(messages)),
        "response_sha256": _sha(reply),
        **({"error": error} if error else {}),
        **({"grounded": True, "source_chunks": [x["chunk_id"] for x in grounding["sources"]],
            "cited": meta["grounding"]["cited"], "invalid_citations": meta["grounding"]["invalid"],
            "retrieval_relevance": grounding["retrieval_relevance"]} if grounding is not None else {}),
    })
    meta["ledger_seq"] = ev.seq
    if meta.get("message_id"):
        with Session(get_engine()) as s:
            m = s.get(Message, meta["message_id"])
            m.meta_json = json.dumps(meta)
            s.add(m)
            s.commit()
    return meta


def _friendly(error: str, model: str, base_url: str) -> str:
    low = error.lower()
    if "connect" in low:
        return f"Can't reach the model server at {base_url}. Check that Ollama is running."
    if "not found" in low or "404" in low:
        return f"Model {model} isn't downloaded on this machine. An admin can pull it or activate another model."
    return f"The model server returned an error: {error}"

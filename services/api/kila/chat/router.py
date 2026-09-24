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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from kila import ledger
from kila.auth.deps import current_user
from kila.db.models import ChatSession, Message, User, utcnow
from kila.db.session import get_engine, get_session
from kila.ledger.chain import canonical_json
from kila.models.registry import ROLES, get_registry
from kila.settings import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])
HISTORY_TURNS = 20


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


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageIn, user: User = Depends(current_user),
                       session: Session = Depends(get_session)) -> StreamingResponse:
    if body.role not in ROLES:
        raise HTTPException(400, f"unknown role {body.role}")
    cs = _own_session(session, session_id, user)
    if not cs.title:
        cs.title = body.content.strip().splitlines()[0][:80]
        session.add(cs)
    session.add(Message(session_id=session_id, role="user", content=body.content))
    session.commit()

    history = session.exec(select(Message).where(Message.session_id == session_id)
                           .order_by(Message.id.desc()).limit(HISTORY_TURNS)).all()[::-1]
    messages = [{"role": "system", "content": _system_prompt()}] + [
        {"role": m.role, "content": m.content} for m in history if m.content
    ]
    spec = get_registry().spec(body.role)
    llm = get_registry().get_llm(body.role)

    async def stream() -> AsyncIterator[str]:
        yield _sse("start", {"role": spec.role, "model": spec.name, "backend": spec.backend.name,
                             "source": spec.source})
        parts: list[str] = []
        usage: dict[str, Any] = {}
        t0 = time.perf_counter()
        t_first: float | None = None
        status, error = "ok", None
        try:
            async for chunk in llm.astream(messages):
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
            meta = _finish(session_id, user, spec, messages, "".join(parts), usage, t0, t_first, status, error)
        if status == "ok":
            yield _sse("done", meta)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


def _finish(session_id: str, user: User, spec, messages: list[dict], reply: str, usage: dict[str, Any],
            t0: float, t_first: float | None, status: str, error: str | None) -> dict[str, Any]:
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

"""SQLModel tables (spec Section 4). `*_json` columns hold JSON text."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    role: str  # engineer | reviewer | admin
    password_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class ChatSession(SQLModel, table=True):
    __tablename__ = "sessions"
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    title: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="sessions.id", index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)
    # Phase 1: which model answered, token counts, timings, ledger seq (assistant messages only).
    meta_json: str = "{}"


class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    id: str = Field(default_factory=new_id, primary_key=True)
    session_id: Optional[str] = Field(default=None, foreign_key="sessions.id", index=True)
    envelope_json: str = "{}"
    task_type: Optional[str] = None
    status: str = "pending"
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class TaskStep(SQLModel, table=True):
    __tablename__ = "task_steps"
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    seq: int
    node: str
    kind: str  # plan | tool_call | tool_result | llm | verify | interrupt
    payload_json: str = "{}"
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None


class RouterDecision(SQLModel, table=True):
    __tablename__ = "router_decisions"
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    task_type: str
    task_conf: float
    difficulty: str
    retrieval_relevance: float
    score: float
    tau: float
    alpha: float
    chosen_model: str
    escalated: bool = False
    latency_ms: float


class Deliverable(SQLModel, table=True):
    __tablename__ = "deliverables"
    id: str = Field(default_factory=new_id, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    object_id: str = Field(foreign_key="objects.id")
    kind: str  # docx | xlsx | pptx | code | json
    status: str = "draft"  # draft | in_review | signed | rejected
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id")
    signed_at: Optional[datetime] = None
    review_comment: Optional[str] = None


class Citation(SQLModel, table=True):
    __tablename__ = "citations"
    id: Optional[int] = Field(default=None, primary_key=True)
    deliverable_id: str = Field(foreign_key="deliverables.id", index=True)
    source_object_id: str = Field(foreign_key="objects.id")
    chunk_id: str
    page: Optional[int] = None
    snippet: str = ""


class Bucket(SQLModel, table=True):
    __tablename__ = "buckets"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    is_public: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class StoredObject(SQLModel, table=True):
    __tablename__ = "objects"
    id: str = Field(default_factory=new_id, primary_key=True)
    bucket_id: int = Field(foreign_key="buckets.id", index=True)
    path: str = Field(index=True)
    sha256: str = Field(index=True)
    size: int
    mime: str
    original_name: str
    uploaded_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=utcnow)
    metadata_json: str = "{}"
    # Soft delete (6.8): rows are never removed, blobs are never unlinked.
    deleted_at: Optional[datetime] = None


class KBDocument(SQLModel, table=True):
    __tablename__ = "kb_documents"
    id: Optional[int] = Field(default=None, primary_key=True)
    object_id: str = Field(foreign_key="objects.id", index=True)
    title: str
    doc_type: str
    indexed_at: Optional[datetime] = None
    chunk_count: int = 0


class LedgerEvent(SQLModel, table=True):
    __tablename__ = "ledger_events"
    seq: Optional[int] = Field(default=None, primary_key=True)
    ts: str  # ISO-8601 UTC string, stored verbatim so hashing is reproducible
    actor: str
    event_type: str = Field(index=True)
    payload_json: str
    prev_hash: str = Field(unique=True)  # one successor per hash -> no forks
    hash: str = Field(unique=True)


class ModelEntry(SQLModel, table=True):
    __tablename__ = "models"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    role: str
    backend: str
    endpoint: Optional[str] = None
    path: Optional[str] = None
    sha256: Optional[str] = None
    signature_ok: bool = False
    active: bool = False
    profile: str = "laptop"


class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    started_at: datetime = Field(default_factory=utcnow)
    config_json: str = "{}"
    results_json: str = "{}"

"""FastAPI entrypoint. Run with a single worker (see docs/ARCHITECTURE.md, ledger writes)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Belt and braces: no library may phone home, even if an env file forgets it.
for _k, _v in {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
    "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "LANGCHAIN_CALLBACKS_BACKGROUND": "false",
    "DO_NOT_TRACK": "1", "ANONYMIZED_TELEMETRY": "False",
}.items():
    os.environ.setdefault(_k, _v)

from kila import __version__, ledger  # noqa: E402
from kila.auth.router import router as auth_router  # noqa: E402
from kila.chat.router import router as chat_router  # noqa: E402
from kila.db.session import run_migrations  # noqa: E402
from kila.ingest import service as ingest_service  # noqa: E402
from kila.ingest.router import router as ingest_router  # noqa: E402
from kila.ledger.router import router as ledger_router  # noqa: E402
from kila.models.registry import get_registry  # noqa: E402
from kila.models.router import router as models_router  # noqa: E402
from kila.rag.router import router as rag_router  # noqa: E402  (importing registers the index listener)
from kila.seed import seed  # noqa: E402
from kila.storage.router import router as storage_router  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    seed()
    get_registry().sync()  # validate models.yaml and mirror its catalog into the DB
    ledger.append("system", "system.startup", {"version": __version__})
    ingest_service.requeue_interrupted()
    yield
    ingest_service.shutdown()
    from kila.rag.store import reset_store

    reset_store()  # release the embedded Qdrant file lock


app = FastAPI(title="KILA API", version=__version__, lifespan=lifespan, docs_url="/docs", redoc_url=None)
app.include_router(auth_router)
app.include_router(storage_router)
app.include_router(ledger_router)
app.include_router(models_router)
app.include_router(chat_router)
app.include_router(ingest_router)
app.include_router(rag_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}

"""FastAPI entrypoint. Run with a single worker (see docs/ARCHITECTURE.md, ledger writes)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

# Belt and braces: no library may phone home, even if an env file forgets it.
for _k, _v in {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
    "LANGCHAIN_TRACING_V2": "false", "DO_NOT_TRACK": "1", "ANONYMIZED_TELEMETRY": "False",
}.items():
    os.environ.setdefault(_k, _v)

from kila import __version__, ledger  # noqa: E402
from kila.auth.router import router as auth_router  # noqa: E402
from kila.db.session import run_migrations  # noqa: E402
from kila.ledger.router import router as ledger_router  # noqa: E402
from kila.seed import seed  # noqa: E402
from kila.storage.router import router as storage_router  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    seed()
    ledger.append("system", "system.startup", {"version": __version__})
    yield


app = FastAPI(title="KILA API", version=__version__, lifespan=lifespan, docs_url="/docs", redoc_url=None)
app.include_router(auth_router)
app.include_router(storage_router)
app.include_router(ledger_router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}

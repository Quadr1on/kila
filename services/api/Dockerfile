# KILA API. Built once while online; runs with no network (internal compose network).
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1 \
    LANGCHAIN_TRACING_V2=false DO_NOT_TRACK=1 ANONYMIZED_TELEMETRY=False \
    KILA_ROOT=/app KILA_DATA_DIR=/data KILA_CONFIG_DIR=/app/config KILA_METRICS_DIR=/metrics

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
# OpenCV (used by OCR preprocessing / RapidOCR) needs these shared libraries at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0     && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY kila ./kila
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home kila && mkdir -p /data && chown kila /data

USER kila
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# One worker: ledger appends are serialised in-process (see docs/ARCHITECTURE.md).
CMD ["/app/.venv/bin/uvicorn", "kila.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

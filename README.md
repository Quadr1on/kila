# KILA

KILA is a sovereign, air-gapped agentic AI workbench built for SIH26117 (MRPL). It runs entirely on
the organisation's own GPU and reads scans, drawings, spreadsheets and code. It drafts
deliverables with citations, and a human reviews and signs them. Every action goes into a
tamper-evident audit ledger.

**Status: Phase 0 (foundations).** See `docs/PHASE_0.md` for what works today and `docs/MOCKS.md` for what doesn't yet.

## Quick start (dev)

Requirements: [uv](https://docs.astral.sh/uv/), Node 20+, and Docker Desktop (for the compose stack).

```
make setup        # Windows: powershell -File scripts/dev.ps1 setup
make dev          # Windows: powershell -File scripts/dev.ps1 dev
```

Open http://localhost:3000 and sign in as `engineer`, `reviewer` or `admin`. The password comes from
`KILA_SEED_PASSWORD` and defaults to `kila-demo`.

## Layout

| Path | What |
|---|---|
| `services/api` | FastAPI backend: `kila/` package, Alembic migrations, tests |
| `apps/web` | Next.js UI |
| `config/` | Behaviour lives in YAML, not code |
| `docs/` | `SPEC.md` (the build brief), `ARCHITECTURE.md`, `MOCKS.md`, `LICENSES.md`, `PHASE_N.md` |
| `data/` | Runtime DB, blobs and keys. Git-ignored. |

Only synthetic data belongs in this repository.

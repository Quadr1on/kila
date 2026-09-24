# KILA: working notes for coding agents

The full build brief is in **docs/SPEC.md**. Read the relevant section before starting a phase.

## Working agreement (from the spec, section 0)

- Build **one phase at a time** (SPEC §9). At the end of each phase, write `docs/PHASE_N.md`, summarise the work, list the mocks, and **stop for approval**.
- **No silent stubs.** Put mocks behind a flag, name them `mock_*`, and list them in `docs/MOCKS.md`. The UI labels anything simulated.
- **Zero runtime egress.** No CDNs, Google Fonts, telemetry, HF downloads or LangSmith. Fonts are local (`apps/web/app/fonts`).
- **Licences:** permissive only. Never PyMuPDF (use pypdfium2), Ultralytics (use RT-DETR or YOLOX) or MinIO. Run `make audit`, and record accepted exceptions in `docs/LICENSES.md` **and** in `scripts/licence_audit.py`.
- **Config over code:** models, thresholds, prompts and tool lists live in `config/*.yaml`.
- Write every important action to the ledger: `kila.ledger.append(actor, event_type, payload)`. Store hashes and ids there, not document text. Commit your own DB work **before** appending.
- Measure, don't claim: numbers come from real runs and are saved to `metrics/`.

## Environment facts

- The host is Windows 11 with an RTX 4060 Laptop GPU (8 GB), so use the `laptop` profile. gVisor, nftables and Tetragon aren't available locally; label the fallbacks honestly.
- Python 3.11 via uv (`services/api/.venv`). Run commands with `uv run --directory services/api ...`.
- Next.js 16: middleware is now `proxy.ts`. We deliberately don't use it, because it buffers upload bodies. The auth guard is in `app/(app)/layout.tsx`.
- The API must run with a single uvicorn worker (ledger writer lock).

## Commands

`make setup | dev | test | audit | build | up` (Windows: `powershell -File scripts/dev.ps1 <task>`).

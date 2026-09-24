# Licences

Policy: permissive only (MIT, Apache-2.0, BSD, ISC, and similar). **Banned:** AGPL/GPL/SSPL/BUSL,
including PyMuPDF/fitz, Ultralytics YOLO and MinIO.

Check: `make audit` (or `scripts/dev.ps1 audit`). The audit walks the installed Python environment
and `apps/web/node_modules`, and writes `metrics/licence_audit.json`. It exits 1 on any denied
licence.

## Direct dependencies (Phase 0)

| Package | Licence | Use |
|---|---|---|
| fastapi, starlette, pydantic, pydantic-settings | MIT | API |
| uvicorn | BSD-3-Clause | ASGI server |
| sqlmodel, sqlalchemy, alembic | MIT | DB + migrations |
| bcrypt | Apache-2.0 | Password hashes |
| itsdangerous | BSD-3-Clause | Signed session cookie |
| cryptography | Apache-2.0 OR BSD-3-Clause | ed25519 ledger signing |
| pillow | MIT-CMU (HPND) | Image thumbnails |
| pypdfium2 (+ PDFium) | Apache-2.0 OR BSD-3-Clause (PDFium: BSD-3) | PDF thumbnails. **Used instead of PyMuPDF.** |
| filetype | MIT | Magic-byte MIME detection |
| python-multipart | Apache-2.0 | Multipart uploads |
| pyyaml | MIT | Config |
| next, react, react-dom | MIT | Web |
| tailwindcss | MIT | Styling (build time) |
| server-only | MIT | Next server-module guard |
| IBM Plex Sans / Mono, Barlow Semi Condensed | SIL OFL 1.1 | Fonts, committed in `apps/web/app/fonts/` with licence files |

## Accepted exceptions (weak copyleft, never linked into KILA code)

| Package | Licence | Reason |
|---|---|---|
| certifi | MPL-2.0 | Unmodified CA bundle. Pulled in by httpx, a dev/test dependency only. |
| lightningcss (+ platform binaries) | MPL-2.0 | Tailwind v4's CSS compiler. Runs at build time and isn't in the runtime image. |
| @img/sharp-* / sharp-libvips | LGPL-3.0 (libvips) | Optional dependency of Next.js for `next/image`, dynamically loaded. KILA doesn't use `next/image`. |

## Planned (later phases, licences verified before adding)

LangGraph/LangChain (MIT), Qdrant (Apache-2.0), bge-m3 and bge-reranker (MIT), PaddleOCR (Apache-2.0),
OpenCV (Apache-2.0), python-docx/openpyxl/python-pptx (MIT), Ollama (MIT), Qwen weights (per model
card; check each tag), Laya (Apache-2.0, to be confirmed in Phase 3), gVisor (Apache-2.0).

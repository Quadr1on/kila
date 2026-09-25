# KILA architecture

Status: **Phase 0** (foundations). Later phases add sections here as they land.

## Processes

```
 browser ──► web (Next.js, :3000) ──/api/*──► api (FastAPI, :8000) ──► SQLite  data/kila.db
                                                                  └─► blobs   data/buckets/<bucket>/objects/aa/bb/<sha256>
```

- The browser only talks to the Next server. `next.config.ts` rewrites `/api/*` to FastAPI, so the
  API port is never published and the `kila_session` cookie is same-origin and httpOnly.
- Auth guard: `app/(app)/layout.tsx` forwards the cookie to `GET /auth/me` on every request. There
  is no Next `proxy.ts` (Next 16's renamed middleware), because a proxy buffers request bodies
  (10 MB default) and would cap uploads.

## Isolation boundary (Docker Compose)

| Network | `internal` | Members | Why |
|---|---|---|---|
| `kila_internal` | **true** | api, web (+ qdrant, ollama later) | Service-to-service only; no route out. |
| `kila_edge` | false | web | Docker won't publish a port for a container that is only on an internal network. |

**Consequence (stated plainly):** `web` sits on a normal bridge as well, so the Next.js container can
technically reach outward. It holds no data and no models; everything sensitive lives in `api`,
which is internal-only. The Phase 7 egress self-test runs from inside `api`. The optional host
nftables policy (Linux) closes the web container's egress too. The web port binds to `127.0.0.1` by default.

## Data

- **SQLite** in WAL mode with `foreign_keys=ON` and `busy_timeout=30s`. Schema lives in
  `kila/db/models.py`, migrations in `kila/db/migrations` (Alembic, `render_as_batch` for SQLite).
  Migrations and the idempotent seed run on API startup.
- `objects.deleted_at` was added to the spec's §4 table so deletes can be soft.

## Hash-chained ledger (`kila/ledger`)

- `hash_n = SHA256(hash_{n-1} ‖ canonical_json({seq, ts, actor, event_type, payload}))`, with
  genesis `SHA256("KILA-GENESIS")`. `seq` is inside the hashed body, so deleting or reordering
  rows is detected too.
- Canonical JSON: sorted keys, `(",", ":")` separators, UTF-8 kept as is (`ensure_ascii=False`), NaN
  forbidden. `ts` is stored as the exact ISO string that was hashed.
- **Writer:** each append is its own short transaction under a process lock, and callers commit their
  own work first. `UNIQUE(prev_hash)` plus the `seq` primary key make a fork impossible even with
  several processes; a losing writer retries. The API runs one uvicorn worker.
- **Verify** (`GET /ledger/verify`) recomputes the whole chain and returns
  `{ok, length, first_bad_seq, reason, head_hash}`. It keeps counting after the first failure, so
  `length` is always the full chain length.
- **Tamper demo** (`POST /ledger/debug/tamper`, admin only, `config/app.yaml: ledger.tamper_demo_enabled`)
  runs a raw `UPDATE` on one row. The original is saved to `data/tamper_backup.json`, and
  `/ledger/debug/restore` puts it back. Both actions are themselves logged.
- **Signed export** (`GET /ledger/export`, admin): all events, plus a manifest (length, head hash,
  verify result, sha256 of the events) signed with ed25519. The key is `data/keys/ledger_ed25519.pem`,
  generated on first use.
- The ledger stores **hashes and identifiers, not document text**.
- Wording: this is a *tamper-evident audit ledger*. It does not prove zero egress; that
  evidence comes from §7 (Phase 7).

## KILA Local Bucket (`kila/storage`)

- Content-addressed blobs `data/buckets/<bucket>/objects/<sha[0:2]>/<sha[2:4]>/<sha256>`. The same
  content in the same bucket is stored once, but each upload gets its own `objects` row.
- Files are streamed to a temp file while hashing, then `os.replace`d into place. The size cap
  comes from `config/app.yaml`.
- MIME type is taken from magic bytes (`filetype`), with Office formats resolved by extension
  (they sniff as ZIP) and text detected as a fallback.
- Per-bucket read/write roles come from `config/app.yaml`. Internal writers (thumbnails, and later
  the deliverable renderer) pass `system=True`.
- Thumbnails (Pillow for images, `pypdfium2` for the first PDF page) are stored as objects in the
  `thumbnails` bucket and linked through `metadata.thumbnail_object_id`.
- Signed URLs are `HMAC-SHA256(secret, "obj:{id}:{exp}")` with a 300 s default and a 3600 s cap.
- Only raster images, PDF, plain text and CSV are served inline. Everything else is sent as
  `application/octet-stream` attachment with `nosniff`, so uploaded HTML or SVG can never run in the
  app's origin.
- **Ledger events:** `storage.upload`, `storage.read` (via `api` or `signed_url`) and
  `storage.delete`, all carrying the sha256. **Exception:** reads from the `thumbnails` bucket are not
  logged (`unlogged_read_buckets`), because every Files page load would flood the ledger with derived
  previews. Thumbnail *writes* are logged.

## Auth

- bcrypt password hashes (the `bcrypt` package directly; passlib is unmaintained).
- The session is an `itsdangerous` timed-signed cookie `{uid}`, httpOnly, `SameSite=Lax`, 12 h.
  It's stateless, so logout clears the cookie but can't revoke a copied token before it expires.
  Acceptable for the MVP, and noted in MOCKS.md.
- Roles: `engineer`, `reviewer`, `admin`. `require_role(...)` is a FastAPI dependency.

## Model plane (Phase 1, `kila/models`, `config/models.yaml`)

- **Roles, not models.** Code calls `get_llm("small_text")`. `ModelRegistry.spec(role)` resolves the
  model in this order: an admin activation (a `models` row with `active=True` for the profile and
  role), then the profile's `default`. If an activated model is later removed from the YAML
  catalog, the registry falls back to the default.
- **Hot reload.** `models.yaml` is re-read when its mtime changes (`${VAR:-default}` env expansion
  is applied), and the reload is logged as `model.config_reloaded`. An activation takes effect on
  the next request with no restart, and is logged as `model.activate`.
- **Client.** `langchain_openai.ChatOpenAI` pointed at `<backend>/v1`, with `stream_usage=True` so
  token counts come from the server. For Ollama, `think: false` becomes `reasoning_effort: "none"`.
  (tiktoken is installed by langchain-openai but never called; token counting would make it
  download encodings, so don't use `get_num_tokens`.)
- **Measurements** (`kila/models/health.py`):
  - The warm-up calls Ollama's native `/api/generate` and takes `load_duration`, `eval_count` and
    `eval_duration` from the response. That gives tokens/sec and load time (the **swap time** when
    the model wasn't resident).
  - Residency and VRAM per model come from `/api/ps`; GPU totals from `nvidia-smi`.
  - Runs are appended to `metrics/model_warmup.json` and logged as `model.warmup`.
- **Chat** (`kila/chat/router.py`): `POST /chat/sessions/{id}/messages` streams SSE events
  (`start`, `delta`, `done` or `error`).
  - The full text is stored in `messages`. `messages.meta_json` (migration 0002) keeps the
    model, token counts, TTFT, tok/s and the ledger seq.
  - The ledger's `llm.call` event holds prompt and response **SHA-256s**, token counts and
    timings, never the text.
  - A dropped connection (the Stop button) saves the partial reply and logs `status: aborted`.
- **Compose:** `ollama` runs on `kila_internal` only, so it can't pull at runtime. Models come
  from `OLLAMA_MODELS_DIR`, which `scripts/predownload.py --yes` fills while online.

## Ingestion (Phase 2, `kila/ingest`, `config/ingest.yaml`)

- Stored object → `Extractor` → `Attachment` (pages, tables, code). `TaskEnvelope` = user text +
  attachments (spec §6.1).
- **Background jobs:** a single worker thread (OCR is CPU-heavy), with state in the `ingestions`
  table (queued/running/done/error, page progress). Jobs interrupted by a restart are re-queued on
  startup.
- **Cache:** a result is reused for identical bytes (sha256 + `PIPELINE` version + language). Bump
  `PIPELINE` whenever extraction output changes.
- **Per type:**

  | Type | How it's read |
  |---|---|
  | Text PDF | pypdfium2 text, normalised, running headers and footers dropped (3+ pages) |
  | Scanned PDF / image | render 200 dpi → OpenCV median denoise + deskew (length-weighted median angle of text-line blobs) → OCR |
  | xlsx / csv | pandas summary (columns, dtypes, preview) + records JSON + a searchable text rendering |
  | docx | python-docx paragraphs and tables |
  | Code / zip | file tree + text, size-capped; `../` paths rejected |

- **OCR = PP-OCR models on RapidOCR/onnxruntime**, not the PaddleOCR package. PaddleOCR 3.x pulled
  in two LGPL packages, a second conflicting OpenCV and a model-download hub. RapidOCR runs the same
  PP-OCR det/rec models with a clean licence footprint.
  - Model paths are always explicit (`kila/ingest/ocr.py`), so RapidOCR's own download code is
    never reached. `test_ocr_never_touches_the_network` blocks non-loopback sockets during OCR.
  - The English/Latin models ship inside the wheel. Devanagari (Hindi) is fetched once by
    `predownload.py`, with its SHA-256 checked. **There's no Kannada PP-OCR model**, so Kannada goes
    to the vision model and the UI says so.
  - The 180° text-line orientation classifier is **off**. It flipped a correct line of a synthetic
    scan into garbage (page accuracy 0.886 → 0.954 with it off). A regression test pins this.
- **Rows:** detections are regrouped into rows by vertical overlap, so a table row reads as one
  line. That matters for retrieval.
- **Vision second opinion:** triggered by a page mean confidence < 0.80, **any** line < 0.75, too
  little text, or Kannada. Both readings are kept, and disagreement (similarity < 0.70) is flagged,
  never silently merged.
- **Page images** are stored in the `thumbnails` bucket (deskewed OCR image, so the confidence-overlay
  boxes line up).
- **PDFium is not thread-safe.** Every pypdfium2 call holds `kila.pdfium_guard.PDFIUM_LOCK`. The lock
  covers only PDFium calls, never OCR. This was found as an access-violation race between thumbnails
  and the OCR worker.

## Retrieval (Phase 2, `kila/rag`, `config/rag.yaml`)

- **Chunks** (`kb_chunks` table): page-bounded, ~300 tokens, cut preferably at section headings,
  then paragraphs and sentences. There's 40-token overlap within prose, but none across a heading.
  Exact character offsets are kept for citations. The id is `"<object_id>:p<page>:<n>"`.
- **Dense:** bge-m3 (1024-d, normalised), with title and heading prefixed to the passage → Qdrant
  **embedded mode** (`data/qdrant`, in-process, file-locked, so a single API worker). Setting
  `qdrant.mode: server` points at a Qdrant server instead.
- **Keyword:** BM25 over the SQLite chunks, rebuilt lazily when the chunk set changes. The tokenizer
  keeps engineering tokens whole (`PV-101`, `0.425`, `H2S`) and also indexes their parts.
- **Fusion:** RRF (k=60) → cross-encoder rerank (bge-reranker-v2-m3, logits → sigmoid) → top 8.
  - On CPU the reranker costs ~0.65 s per passage (measured), so it reranks the top **8** on CPU
    and the top **30** on GPU (the spec's value).
  - `retrieval_relevance` = best reranked score (0..1), which the Phase 3 router uses.
- **Scope:** knowledge-base search is limited to the `kb` bucket. Chat attachments are indexed too,
  but searched only when attached (`object_ids` filter). Deleted objects are filtered out at read
  time.
- **Grounded chat:** retrieve → numbered sources `[S1]…` in the prompt (with
  `config/prompts/grounded_answer.md`, temperature 0) → SSE `status` / `sources` events → the
  answer → citation check (cited / invalid / uncited). The ledger records chunk ids, citations and
  relevance, never the question or the source text.

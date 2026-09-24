# KILA — Master Build Prompt (SIH26117 MVP)

> Paste this whole file into your AI coding assistant as the project brief (or save it as `CLAUDE.md` / `AGENTS.md` at the repo root). Work through it **one phase at a time**. At the end of each phase, stop, summarise what was built, list anything mocked, and wait for approval before starting the next phase.

---

## 0. Role and working agreement

You are a senior full-stack + ML engineer building **KILA**, a sovereign, air-gapped, agentic AI workbench, as a hackathon MVP for Smart India Hackathon 2026, problem statement **SIH26117** (MRPL, Mangalore Refinery & Petrochemicals Ltd).

Target: a demo that is **70–80% real**. Every feature shown in the demo must actually run end to end on local hardware. Where something is simulated, the UI must label it as simulated.

Rules you must follow throughout:

1. **Build in phases** (Section 9). Do not start a phase until the previous one passes its acceptance checks.
2. **No silent stubs.** If you mock something, put it behind a flag, name it `mock_*`, and list it in `docs/MOCKS.md`.
3. **Zero runtime egress.** Nothing may call the internet at runtime: no CDNs, no Google Fonts, no telemetry, no HuggingFace downloads, no LangSmith. See Section 7.
4. **Licence hygiene.** Only permissive licences (MIT, Apache-2.0, BSD). Banned: **PyMuPDF/fitz (AGPL)** → use `pypdfium2`; **Ultralytics YOLO (AGPL)** → use RT-DETR via `transformers`, YOLOX, or classical CV; **MinIO (AGPL)**. Keep `docs/LICENSES.md` updated and add a script that audits Python and npm dependencies.
5. **Config over code.** Models, thresholds, prompts and tool lists live in YAML under `config/`. Swapping a model must not require code changes.
6. **Everything important is logged to the hash-chained ledger** (Section 6.7).
7. **Measure, don't claim.** Latency, router escalation rate and eval accuracy must come from real runs, saved to `metrics/`.
8. Write tests for core logic (router, ledger, storage, tools). Keep them fast and offline.
9. Prefer simple, readable code over clever abstractions. This is a hackathon MVP.

---

## 1. Problem context

Refineries, PSUs and defence-linked manufacturing units handle confidential knowledge work: P&IDs, engineering calculations, scanned inspection reports, vendor correspondence, financials and internal code. This data cannot legally or contractually be sent to cloud AI (ChatGPT, Claude, etc.). Today staff either work manually (slow) or paste data into public tools (a policy breach).

KILA gives them a Claude/Codex-like assistant that:

- runs **entirely on the organisation's own GPU**, with no external network;
- accepts **multimodal input**: scans, handwriting, photos, PDFs, spreadsheets, code;
- **plans and uses tools** (agentic), rather than just chatting;
- produces **finished deliverables**: `.docx`, `.xlsx`, `.pptx`, code, all with citations and the steps shown;
- routes each task to the **right open-weight model** (small by default, escalating to a bigger one only when needed);
- keeps a **tamper-evident audit ledger** and shows live proof of network isolation;
- **never approves anything.** KILA drafts, and a human reviews and signs.

---

## 2. Tech stack (fixed unless noted)

| Layer | Choice | Notes |
|---|---|---|
| Frontend | **Next.js (App Router) + React + TypeScript + Tailwind** | No external fonts or CDNs. Use `next/font/local` only. `NEXT_TELEMETRY_DISABLED=1`. |
| Backend API | **FastAPI (Python 3.11)** | All ML/agent code is Python. Stream agent events to the UI over SSE. |
| Agent orchestration | **LangGraph** (+ minimal LangChain) | Explicit state graph, `SqliteSaver` checkpointer, `interrupt()` for human-in-the-loop, subgraphs for subagents. Don't use legacy `AgentExecutor`. |
| LLM client | `langchain-openai` `ChatOpenAI` pointed at a **local OpenAI-compatible server** | One interface for Ollama, llama.cpp/llama-swap and vLLM. |
| Model serving | **Profile-based**: Ollama or llama-swap on small GPUs; **vLLM** on 24 GB+ | See Section 5. |
| Task classifier + router signal | **Laya** (`convaiinnovations/laya`, Apache-2.0) via `pip install laya` | Calibrated typed decisions. Use the multilingual checkpoint for non-English input. See Section 6.2. |
| Database | **SQLite** (WAL mode) via SQLModel/SQLAlchemy + Alembic | A single file at `data/kila.db`. |
| File storage | **KILA Local Bucket**: a content-addressed store on disk + SQLite metadata | Supabase-Storage-like API. See Section 6.8. |
| Vector DB | **Qdrant** (Docker, telemetry disabled) or `qdrant-client` local mode for dev | Hybrid retrieval: dense + BM25 → RRF → reranker. |
| Embeddings / reranker | `BAAI/bge-m3` (multilingual) + `BAAI/bge-reranker-v2-m3` | Pre-download; load from local path. |
| OCR / CV | **PaddleOCR** + **OpenCV** | Pre-download OCR weights. Enable Hindi/Kannada OCR models if available. |
| PDF | `pypdfium2` (render + text) | Never PyMuPDF. |
| Deliverables | `python-docx`, `openpyxl`, `python-pptx` | Template-based. |
| Code sandbox | **gVisor (`runsc`)** on Linux; fallback Docker `runc` with hardening | See Section 6.6. |
| Packaging | **Docker Compose** with an `internal: true` network | See Section 7. |

> **Note on the PPT:** the deck says "66M DistilBERT, <10 ms" and "Hermes Agent". The MVP uses **Laya (≈320–420M, ~33 ms on GPU)** and **LangGraph**. Update the slides to match what is actually built.

---

## 3. Repository layout

```
kila/
├─ apps/
│  └─ web/                     # Next.js frontend
├─ services/
│  ├─ api/                     # FastAPI app (routers, auth, SSE)
│  │  └─ kila/
│  │     ├─ agent/             # LangGraph graphs, nodes, subagents, prompts
│  │     ├─ router/            # Laya classifier + cascade router
│  │     ├─ models/            # model registry, LLM client factory, health
│  │     ├─ ingest/            # multimodal ingestion → TaskEnvelope
│  │     ├─ rag/               # chunking, embeddings, qdrant, bm25, rrf, rerank
│  │     ├─ tools/             # agent tools (docx/xlsx/pptx, calc, rag, sandbox, pid)
│  │     ├─ pid/               # P&ID digitiser (CV + OCR + VLM)
│  │     ├─ storage/           # KILA Local Bucket
│  │     ├─ ledger/            # hash-chained audit ledger
│  │     ├─ sovereignty/       # egress self-test, network status, model import
│  │     ├─ db/                # SQLModel models, session, migrations
│  │     └─ eval/              # golden set runner, metrics
│  └─ sandbox/                 # sandbox runner image (Dockerfile + runner script)
├─ config/
│  ├─ models.yaml              # model pool + profiles
│  ├─ router.yaml              # Laya questions, α, τ, temperatures
│  ├─ tools.yaml               # which tools each task type can use
│  └─ prompts/                 # system prompts per task type
├─ templates/                  # docx/xlsx/pptx templates (fictional letterhead)
├─ seed/                       # SYNTHETIC corpus only (SOPs, reports, P&IDs, sheets)
├─ scripts/                    # setup, predownload, licence audit, demo recorder
├─ infra/                      # docker-compose.yml, nftables rules, tetragon policy
├─ metrics/                    # generated benchmark + eval outputs (JSON)
└─ docs/                       # ARCHITECTURE.md, MOCKS.md, LICENSES.md, DEMO.md
```

---

## 4. Data model (SQLite)

Create these tables with SQLModel. Add fields only if a phase needs them.

- `users` (id, name, role: `engineer` | `reviewer` | `admin`, password_hash, created_at)
- `sessions` (id, user_id, title, created_at)
- `messages` (id, session_id, role, content, created_at)
- `tasks` (id, session_id, envelope_json, task_type, status, created_at, finished_at)
- `task_steps` (id, task_id, seq, node, kind: `plan` | `tool_call` | `tool_result` | `llm` | `verify` | `interrupt`, payload_json, started_at, ended_at)
- `router_decisions` (id, task_id, task_type, task_conf, difficulty, retrieval_relevance, score, tau, alpha, chosen_model, escalated bool, latency_ms)
- `deliverables` (id, task_id, object_id, kind: `docx` | `xlsx` | `pptx` | `code` | `json`, status: `draft` | `in_review` | `signed` | `rejected`, reviewer_id, signed_at, review_comment)
- `citations` (id, deliverable_id, source_object_id, chunk_id, page, snippet)
- `buckets` (id, name, is_public=false, created_at)
- `objects` (id, bucket_id, path, sha256, size, mime, original_name, uploaded_by, created_at, metadata_json)
- `kb_documents` (id, object_id, title, doc_type, indexed_at, chunk_count)
- `ledger_events` (seq PK autoincrement, ts, actor, event_type, payload_json, prev_hash, hash)
- `models` (id, name, role, backend, endpoint, path, sha256, signature_ok, active, profile)
- `eval_runs` (id, started_at, config_json, results_json)

---

## 5. Model pool and hardware profiles

`config/models.yaml` defines **roles** and **profiles**. The code only asks for a role; the active profile decides which model serves it.

Roles:

- `small_text`: default for most tasks
- `large_text`: escalation target for hard reasoning
- `coder`: code tasks
- `vision`: VLM for scans, photos and P&ID description
- `embedder` and `reranker`: RAG

Profiles (fill in actual model tags after checking what is current and what fits in VRAM):

```yaml
active_profile: laptop   # laptop | workstation | server

profiles:
  laptop:        # <= 8 GB VRAM. Ollama or llama-swap, ONE model resident, swap on demand
    small_text:  { backend: ollama, model: "<qwen3 ~4B instruct, Q4>" }
    large_text:  { backend: ollama, model: "<qwen3 ~8B instruct, Q4>" }
    coder:       { backend: ollama, model: "<qwen coder ~7B, Q4>" }
    vision:      { backend: ollama, model: "<qwen VL ~3–8B, Q4>" }
  workstation:   # 24 GB
    ...
  server:        # 48–80 GB, vLLM, AWQ INT4
    large_text:  { backend: vllm, model: "<~30–70B AWQ>", endpoint: "http://vllm-reason:8000/v1" }
    ...
```

Requirements:

- A `ModelRegistry` that loads the YAML, exposes `get_llm(role)` returning a `ChatOpenAI` pointed at the right base URL, and hot-reloads when the YAML changes or an admin clicks "activate".
- A `/models` endpoint and UI page listing each role, the model serving it, health, VRAM (from `nvidia-smi` if available), and tokens/sec measured by a warm-up call.
- **Be honest about VRAM.** If models cannot all be resident, use swap mode, and measure and display the swap time. Do not claim everything runs at once if it doesn't.
- For vLLM with Qwen tool calling, launch with `--enable-auto-tool-choice --tool-call-parser hermes` (verify the flag for the version in use).
- Small models are unreliable at free-form tool calling. Prefer **structured JSON outputs validated by Pydantic** with one retry on validation failure, plus a deterministic executor (Section 6.4).

---

## 6. Feature specifications (mirror the PPT)

### 6.1 Multimodal ingestion → TaskEnvelope  *(PPT: "Multimodal Ingestion")*

Input: a user message plus zero or more attachments (image, scanned PDF, text PDF, docx, xlsx/csv, code files, zip of code).

Pipeline:

1. Store every attachment in the Local Bucket (`uploads` bucket) and log it to the ledger.
2. Detect the type by MIME and magic bytes.
3. Extract content by type:
   - **Text PDF:** use `pypdfium2` text per page. **Scanned PDF or image:** render pages, deskew and denoise with OpenCV, then run PaddleOCR (text + boxes + confidence).
   - **Handwriting:** run OCR; if the average confidence is low, also send the image to the `vision` model for a transcription. Keep both outputs and flag disagreement.
   - **xlsx/csv:** read with `openpyxl`/`pandas` into a sheet summary (headers, dtypes, first N rows) plus the raw table stored as JSON.
   - **Code:** file tree plus contents (size-capped).
4. Output a Pydantic `TaskEnvelope`:
   ```
   {id, user_text, language, attachments:[{object_id, kind, pages:[{text, ocr_conf, image_object_id}], table?, code?}], created_at}
   ```
5. Show an **ingestion preview** in the UI: page thumbnails, extracted text, and OCR confidence heat.

### 6.2 Task classifier with Laya  *(PPT: "Task Classifier")*

Use `laya.Router(preload=True, device=...)`. It picks the English or multilingual checkpoint automatically. Hindi/Kannada input is a selling point, so demo it.

Questions (in `config/router.yaml`):

```yaml
questions:
  task_type:
    type: choice
    instructions: "What kind of work is the user asking for?"
    criteria:
      approval_note: "draft an approval/recommendation note from reports or data"
      inspection_summary: "summarise or extract findings from an inspection report"
      engineering_calc: "perform or verify an engineering calculation"
      pid_digitise: "read or digitise a P&ID / engineering drawing"
      code_task: "write, fix or explain code"
      correspondence: "draft or reply to a letter/email/vendor message"
      sheet_analysis: "analyse or transform spreadsheet data"
      general_qa: "question answerable from the knowledge base"
  difficulty:
    type: choice            # use choice, NOT score (score is Laya's weakest primitive)
    instructions: "How hard is this task to do correctly?"
    criteria: { low: "routine, single step", medium: "several steps", high: "multi-step reasoning, calculations, or high stakes" }
  needs_vision:
    type: choice            # use choice, NOT noul (known noul label-bias issue)
    instructions: "Does the task require looking at an image, scan, or drawing?"
    criteria: { A: "yes, visual content is essential", B: "no, text is enough" }
```

The classifier state is `{user_text, attachment summaries (first ~300 tokens), file kinds}`.

Laya caveats you must handle:

- **Base checkpoints are weak zero-shot and ship over-confident.** Build a labelled set of 200–400 synthetic requests (`seed/router_labels.jsonl`, spread across all task types, some in Hindi/Kannada). Fit a **temperature per question** on it and save it to `router.yaml`. Report accuracy and ECE before and after calibration in `metrics/router_calibration.json`.
- **Gate on `confidence`, never on `action.act_probability`** (documented as carrying no usable signal).
- Optional stretch: fine-tune using Laya's fine-tuning notebook if the base accuracy is poor.
- Pre-download the checkpoints, and set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

### 6.3 Cascade router  *(PPT: "Confidence-Calibrated Cascade Router")*

1. Classify with Laya → `task_type`, `task_conf`, `difficulty`, `needs_vision`.
2. Retrieve top-k context (6.5) → `retrieval_relevance` = top reranker score, normalised to 0–1.
3. Compute `score = α·task_conf + (1−α)·retrieval_relevance`.
4. Pick the model role:
   - `needs_vision` → `vision` first (for perception), then a text role for writing.
   - `code_task` → `coder`.
   - Otherwise → `small_text`.
5. **Escalate to `large_text`** if `score < τ`, or `difficulty == high`, or the verifier (6.4) fails on the small model's output (at most one escalation per task).
6. Tune α and τ on the eval set (Section 8), and store them in `router.yaml`.
7. Persist every decision to `router_decisions` and the ledger, and show it in the UI step timeline, e.g. *"doc_understand · conf 0.81 · relevance 0.88 · score 0.84 ≥ τ 0.70 → small_text"*.
8. Add a **Router analytics** page: escalation rate, per-model share, average latency, and accuracy on the eval set.

### 6.4 Agent tool loop in LangGraph  *(PPT: "Agent Tool-Loop", "subagent checks calc")*

Graph state: `{envelope, route, plan, steps[], context_chunks[], drafts[], verification, deliverable_ids[], needs_human}`.

Nodes:

1. `classify_and_route` (6.2 + 6.3)
2. `retrieve`: hybrid RAG (6.5), plus the user's attachments as context
3. `plan`: LLM returns a **JSON plan** (Pydantic-validated): an ordered list of `{step, tool, args, purpose}` drawn from the tools allowed for this `task_type` in `config/tools.yaml`
4. `execute`: a deterministic loop that runs each tool, records `task_steps`, and streams events over SSE. If a step fails, re-plan once.
5. `draft`: LLM writes the deliverable content as structured JSON (sections, tables, citations referencing chunk ids)
6. `verify` (**subagent**, a LangGraph subgraph):
   - extracts every numeric claim and calculation from the draft;
   - recomputes them in the **sandbox** (6.6) with Python;
   - checks that every citation id exists and that the snippet actually supports the claim (a small LLM judge);
   - returns `{passed, issues[]}`. On failure, fix and retry once, then escalate the model once, then surface the issues to the user.
7. `render`: builds the `.docx`/`.xlsx`/`.pptx` from templates, stores it in the `deliverables` bucket, and writes `deliverables` and `citations` rows
8. `human_review`: LangGraph `interrupt()`. The deliverable stays `draft` / `in_review` until a `reviewer` signs or rejects it in the UI. **KILA can never set `signed`.**

Tools (each a typed function, each logged to the ledger):

- `rag_search(query, k)`
- `read_attachment(object_id, page?)`
- `ocr_image(object_id)`
- `vision_describe(object_id, question)`
- `calc_python(code)` (sandboxed)
- `sheet_query(object_id, pandas_expr)` (sandboxed)
- `make_docx(spec)`, `make_xlsx(spec)`, `make_pptx(spec)`
- `pid_digitise(object_id)` (6.9)
- `code_run(files, cmd)` (sandboxed)

Use the `SqliteSaver` checkpointer so a task survives a backend restart and the human-review pause.

### 6.5 Local RAG  *(PPT: "Qdrant · BM25 hybrid · RRF · bge-reranker")*

- Build the knowledge base from the `kb` bucket (SOPs, standards, past reports, all synthetic).
- Chunk by heading/page, ~400–600 tokens with overlap. Keep `object_id`, page and char offsets for citations.
- Dense: `bge-m3` → Qdrant. Sparse: BM25 (`rank_bm25`, or Qdrant sparse vectors).
- Fuse with **Reciprocal Rank Fusion** (k=60), then rerank the top 30 with `bge-reranker-v2-m3` and keep the top 8.
- Add a **Knowledge base** UI page: upload, index status, and a search playground showing dense, BM25, fused and reranked results side by side.

### 6.6 Sandbox  *(PPT: "gVisor · seccomp")*

- A runner image with Python + numpy/pandas/sympy and nothing network-related.
- Launch per call through the Docker SDK:
  - `runtime="runsc"` when gVisor is available, otherwise `runc`;
  - `network_mode="none"`, `read_only=True`, a tmpfs work dir, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges", seccomp profile]`;
  - `pids_limit`, memory and CPU limits, and a 20 s timeout.
- Show which runtime was used in the step timeline (`gVisor` vs `runc (fallback)`), and label it honestly.
- Log stdout/stderr hashes and the exit code to the ledger.
- Include a test that tries `socket.connect(("1.1.1.1", 443))` inside the sandbox and asserts failure.
- On Windows, the sandbox requires Docker Desktop with WSL2. gVisor itself is Linux-only, so document this.

### 6.7 Hash-chained ledger  *(PPT: "Hash-Chained Zero-Egress Ledger")*

- Compute `hash_n = SHA256(hash_{n-1} || canonical_json(event))`. The genesis hash is `SHA256("KILA-GENESIS")`.
- Append-only writer with a single lock. Events include: file upload/read, ingestion, router decision, every LLM call (model, prompt hash, token counts, latency), every tool call, sandbox run, deliverable status change, model activation, egress self-test result, and login.
- Store prompt and response **hashes**, not full text, in the ledger. Full text lives in `task_steps`.
- `GET /ledger/verify` recomputes the whole chain and returns `{ok, length, first_bad_seq}`.
- **Tamper demo:** an admin-only debug button edits one row directly in SQLite. `verify` must then flag it and the UI must show the break.
- Export a signed ledger snapshot (ed25519) for audit.
- **Wording in the UI and docs:** call it a *"tamper-evident audit ledger"*, not "cryptographic proof of zero egress". The isolation evidence comes from 7.

### 6.8 KILA Local Bucket (Supabase-Storage-like, fully local)

- Buckets: `uploads`, `kb`, `deliverables`, `pid`, `models` (metadata only), `thumbnails`.
- Content-addressed layout: `data/buckets/<bucket>/objects/<sha[0:2]>/<sha[2:4]>/<sha256>`, deduplicated by hash. Metadata goes in the `objects` table.
- API (FastAPI):
  - `POST /storage/{bucket}/upload` (multipart) → `{object_id, sha256, path}`
  - `GET /storage/{bucket}/list?prefix=`
  - `GET /storage/object/{object_id}` streams the file with a proper MIME type. Access requires auth plus a bucket-level role check.
  - `POST /storage/object/{object_id}/signed-url?expires=300` → an HMAC-signed short-lived URL, for `<img>`/`<iframe>` previews
  - `DELETE /storage/object/{object_id}` → soft delete only (keep the audit trail)
- Generate image and PDF-page thumbnails on upload.
- A small TS client in `apps/web/lib/storage.ts` with a Supabase-like API: `storage.from('kb').upload(file)`, `.list()`, `.getSignedUrl(id)`.
- Every read and write goes to the ledger with the sha256. Deliverables list their source object hashes, which gives provenance.

### 6.9 P&ID digitiser — CV + VLM hybrid  *(PPT: "CV+VLM Hybrid P&ID Digitiser")*

This is KILA's **most domain-specific feature**, so make it visually strong.

MVP pipeline, in order of priority:

1. **Preprocess** (OpenCV): binarise, deskew, remove the border and title block.
2. **Text/tag extraction** (PaddleOCR): detect tag-like strings with a regex, e.g. `^[A-Z]{1,4}-?\d{2,5}[A-Z]?$` (such as `PV-101`, `FT-2031`), line numbers, and notes.
3. **Line detection** (OpenCV Hough / morphological line extraction): detect horizontal and vertical process lines and merge collinear segments.
4. **Symbol detection** (stretch): template matching for 5–8 common symbols (valve, pump, instrument bubble, tank, heat exchanger), or a permissively licensed detector (RT-DETR/YOLOX) trained on synthetic P&IDs. No Ultralytics.
5. **Graph build**: nodes = tags/symbols, edges = lines connecting them (by proximity to line endpoints). Export as JSON.
6. **VLM pass**: send the image plus the extracted tag list and graph to the `vision` model and ask for a structured description. The VLM must reference only extracted tags; flag any tag it mentions that was not extracted.
7. Outputs:
   - an `.xlsx` tag register (tag, type, page, bbox, connected_to);
   - the graph JSON;
   - an annotated overlay image;
   - a short description.
8. UI: the original drawing with a toggleable overlay (boxes for tags and symbols, coloured lines). Clicking a tag highlights its connections.

Use **synthetic or openly licensed P&IDs only** (`seed/pid/`). Never use real MRPL drawings.

### 6.10 Human sign-off and roles

- Roles: `engineer` creates tasks; `reviewer` signs or rejects deliverables; `admin` manages models, users and the ledger.
- Every rendered deliverable carries a watermark/footer: *"DRAFT — AI-assisted. Requires human review and signature."* Once signed, re-render with the reviewer name and timestamp, and remove the draft watermark.
- The **Approvals** page lists the review queue with a side-by-side view: deliverable preview, citations, verification report and step timeline.
- Local auth only (username + password, bcrypt, httpOnly session cookie). No OAuth, no external IdP.

### 6.11 Model-update channel  *(PPT: "1-way diode · SHA256 + sig · admin promotes")*

- `scripts/staging_bundle.py` runs on a connected machine. It downloads a model, then writes a bundle containing the weights, `manifest.json` (file hashes, role, licence) and `manifest.sig` (ed25519).
- `POST /models/import` in the air-gapped app reads the bundle from a local path. It verifies every sha256 and the signature against a pinned public key, registers the model as **inactive**, and logs to the ledger.
- The admin clicks **Activate** → hot swap (5). A **Rollback** button is available.
- The UI labels the physical "one-way diode" as *out of scope for the demo (simulated by offline bundle transfer)*.

---

## 7. Sovereignty and isolation (must be real)

1. **Docker Compose networking:** put all services on one network with `internal: true`. Services can talk to each other; nothing can reach outside. Only the web UI port is published to the host (localhost only by default).
   - Do **not** use `network_mode: none` on the core services, because they need to talk to each other. Use it only for sandbox containers.
2. **Disable all telemetry and downloads via env:**
   - `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`
   - `LANGCHAIN_TRACING_V2=false`, and no `LANGSMITH_*` keys
   - `NEXT_TELEMETRY_DISABLED=1`
   - `QDRANT__TELEMETRY_DISABLED=true`
   - `DO_NOT_TRACK=1`
   - PaddleOCR model dirs pointed at local paths; Ollama with no pulls at runtime
3. **Offline setup:** `scripts/predownload.py` fetches every model and weight **once** during setup, into `models/`. After that the whole stack must start with networking fully off.
4. **Egress self-test** (`POST /sovereignty/egress-test`), run from inside the API container:
   - a DNS lookup of a public domain;
   - a TCP connect to a public IP:443;
   - an HTTPS GET to a public URL.

   All three must **fail**. Record each result in the ledger and show a green "Isolated" badge with a timestamp. Also run the test automatically on startup and every N minutes.
5. **Host firewall (Linux, optional but recommended):** `infra/nftables.conf` with a default-DROP output policy except loopback and the Docker bridge, plus instructions.
6. **eBPF audit (stretch, Linux only):** a Tetragon TracingPolicy that watches `connect()`/`sendto()` syscalls from KILA containers. A small collector forwards events into the ledger. If it isn't built, the UI must not claim it.
7. **Sovereignty dashboard** page showing:
   - the network status of each container;
   - the last egress-test results;
   - ledger length and the verify button;
   - the tamper demo;
   - the list of models with hashes and signature status.

   Include a **"pull the cable" demo mode**: the UI keeps working with the host's Wi-Fi/ethernet disabled.

---

## 8. Evaluation and metrics (for slides and judges)

- `seed/golden/`: 20–40 golden tasks across all task types, each with expected facts or numbers, the expected task_type, and acceptance checks.
- `python -m kila.eval.run` executes all of them and writes `metrics/eval_<date>.json` with:
  - task-type accuracy;
  - verifier pass rate;
  - numeric correctness;
  - citation validity;
  - escalation rate;
  - p50/p95 end-to-end latency per task type;
  - tokens/sec per model;
  - Laya latency.
- Also sweep α and τ and report the accuracy-vs-escalation trade-off (a table plus a chart on the Router analytics page).
- These numbers replace the borrowed benchmark figures in the PPT.

---

## 9. Build phases

Each phase ends with a **demoable state**, a passing test suite, and a short `docs/PHASE_N.md` covering what was built, what's mocked and how to run it.

### Phase 0: Foundations
- Monorepo scaffold (Section 3), Docker Compose with the internal network, `.env.example`, a Makefile (`make setup`, `make dev`, `make test`, `make offline-check`).
- SQLite + SQLModel + Alembic with the Section 4 tables.
- **Ledger** (6.7) with unit tests for chaining, verification and tamper detection.
- **Local Bucket** (6.8) with its API, thumbnails, signed URLs and tests.
- Local auth + roles, and seeded users (`engineer`, `reviewer`, `admin`).
- Next.js shell: login, sidebar, empty pages for Workbench, Files, Knowledge Base, Approvals, Models, Router, Sovereignty, Eval.
- **Accept when:** you can upload a file in the Files page, preview it, see it in the ledger, and `verify` returns ok.

### Phase 1: Model plane
- `models.yaml` profiles, `ModelRegistry`, the `get_llm(role)` factory, health and tokens/sec warm-up.
- `scripts/predownload.py` (models, Laya, bge-m3, reranker, PaddleOCR).
- A basic streaming chat on `small_text` (SSE → UI), with every call logged to the ledger.
- Models page with Activate/hot-swap.
- **Accept when:** you can chat with a local model while networking is off, and swapping `small_text` in the UI takes effect without a restart.

### Phase 2: Ingestion + RAG
- Ingestion pipeline (6.1) with the preview UI.
- Knowledge base indexing and hybrid retrieval (6.5) with the search playground.
- Seed the synthetic corpus: 10–20 SOPs/standards, 5 scanned-style inspection reports (generate PDFs, then add scan noise), 2 spreadsheets, a small code folder.
- **Accept when:** you can upload a scanned report, see its OCR text, ask a question about it, and get an answer with page-level citations.

### Phase 3: Laya classifier + cascade router
- Laya integration (6.2) plus the labelled set, temperature fitting and calibration metrics.
- Cascade router (6.3) with `router_decisions`, step timeline entries and the Router analytics page.
- **Accept when:** 20 mixed prompts (including Hindi/Kannada) are routed with the decisions visible, calibration metrics are saved, and escalation visibly happens on hard or low-relevance prompts.

### Phase 4: Agent + deliverables + human sign-off
- The LangGraph graph (6.4) with plan → execute → draft → verify → render → human_review.
- docx/xlsx/pptx templates and rendering, citations and watermark.
- A Workbench UI with a live **step timeline** (plan, tool calls, router decision, verification), a deliverable preview (render docx/pptx pages to images for preview) and download.
- Approvals page with sign/reject (6.10).
- **Accept when:** *scanned inspection report → approval_note.docx with citations → verifier passes → reviewer signs*, fully offline, with every step in the ledger.

### Phase 5: Sandbox + calc verification + code tasks
- The sandbox runner (6.6) with gVisor detection and fallback.
- `calc_python`, `sheet_query` and `code_run` tools, plus a verifier subagent that recomputes the numbers.
- **Accept when:** an engineering calculation task produces an xlsx; the verifier catches a deliberately wrong number (via a test mode that injects an error) and fixes it; the in-sandbox network test fails as expected.

### Phase 6: P&ID digitiser
- The 6.9 pipeline, stages 1–3 and 5–7 required, stage 4 as a stretch.
- The overlay viewer UI.
- **Accept when:** a synthetic P&ID produces a tag register xlsx, a graph JSON and an overlay, and the VLM description only references extracted tags.

### Phase 7: Sovereignty hardening
- Egress self-test, Sovereignty dashboard, tamper demo, offline-check script, nftables file, and the model import/verify/activate/rollback flow (6.11).
- Tetragon as a stretch.
- `make offline-check`: brings the stack up with the host network down and runs a smoke test of every feature.
- **Accept when:** everything in Phases 0–6 works with networking disabled, and the dashboard shows green isolation plus a verified ledger.

### Phase 8: Eval, polish, demo
- The golden set and eval runner (8), with metrics pages.
- `docs/DEMO.md` with a 5–7 minute demo script (below), and `scripts/record_demo` (optional).
- UI polish, empty and error states, loading states, and seed/reset buttons.
- **Accept when:** the demo script runs start to finish on the target hardware, and the metrics JSON exists for the slides.

---

## 10. Demo script (what the judges see)

1. **Isolation first:** open the Sovereignty dashboard, pull the network cable/disable Wi-Fi, run the egress test (all blocked), and verify the ledger.
2. **Inspection report → approval note:** upload a scanned report (optionally with a Hindi handwritten remark). Show:
   - the router decision (Laya confidence, relevance, chosen model);
   - the plan and tool calls in the step timeline;
   - the verifier recomputing a number;
   - the `.docx` with citations.

   The reviewer then signs it.
3. **P&ID:** upload a drawing and show the overlay, tag register xlsx and connection graph.
4. **Code/calc task in the sandbox:** show the runtime label and that the in-sandbox network call is blocked.
5. **Model hot-swap:** import a signed bundle, activate it, and re-run a prompt.
6. **Tamper demo:** edit a ledger row, and verify shows the break at the exact seq.
7. **Metrics slide:** your own measured latency, escalation rate and eval accuracy.

---

## 11. Definition of done for the MVP

- [ ] All of Phases 0–7 pass their acceptance checks with the network off
- [ ] Every UI claim matches what actually runs, and simulated parts are labelled
- [ ] The licence audit passes (no AGPL)
- [ ] `metrics/` contains real eval, router-calibration and latency numbers
- [ ] `docs/MOCKS.md` lists every mock
- [ ] Only synthetic data is in the repo
- [ ] One-command start: `docker compose up -d` (after `make setup` has pre-downloaded models)

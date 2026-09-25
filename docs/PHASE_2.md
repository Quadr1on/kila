# Phase 2: Ingestion + retrieval

## Built

- **Multimodal ingestion** (`kila/ingest`) → `TaskEnvelope`: text and scanned PDFs, images, xlsx/csv, docx, code and zip.
  - Background worker with page progress.
  - Content-hash cache: identical files are never OCR'd twice.
  - Jobs interrupted by a restart are re-queued.
  - Ledger events: `ingest.queued`, `ingest.done`, `ingest.cache_hit`, `ingest.failed`.
- **OCR:** PP-OCR models run by RapidOCR on onnxruntime, after OpenCV denoise + deskew.
  - Table rows are rebuilt from cell detections.
  - Hindi (Devanagari) OCR works. Kannada goes to the vision model and is labelled as such.
  - A **vision-model second opinion** runs on weak pages or weak lines; disagreements are flagged, never merged.
  - OCR provably never touches the network: a test blocks all non-loopback sockets while it runs.
- **Retrieval** (`kila/rag`), all in-process:
  - page-bounded, heading-aware chunks with exact character offsets;
  - bge-m3 → Qdrant (embedded mode), plus BM25;
  - RRF fusion, then bge-reranker.
  - Every stage and its timing is returned, plus a 0–1 `retrieval_relevance` for the Phase 3 router.
- **Grounded answers in chat:** attach files and/or search the knowledge base.
  - The stream is: retrieval → numbered sources → an answer citing `[S#]` → citation check (cited / invalid / uncited).
  - The ledger records chunk ids and citations, not text.
- **Synthetic seed corpus** (`scripts/make_seed_corpus.py`), all fictional ("Konkan Coastal Refinery"):
  - 12 SOPs and standards;
  - 5 inspection reports with scan damage, plus exact ground-truth text;
  - 2 spreadsheets and a small code package.
- **UI:**
  - **Document view** (`/files/[id]`): page images with an **OCR confidence heat overlay** (hover a box to see what was read), extracted text, the vision second reading, sheet previews and a code browser.
  - **Knowledge base:** upload with automatic indexing, **Load demo corpus** (admin), per-document read and index status, and a **search playground** with Dense / BM25 / Fused / Reranked side by side, cross-highlighting and stage timings.
  - **Workbench:** attach files (upload → read → index, with live status), a "Search the knowledge base" toggle, a *Searching documents…* state, clickable `S1` citation chips that open the cited page, and a Sources panel that flags uncited or invalid citations.
- **Robustness fixes found along the way:**
  - **PDFium thread-safety race** (access violation): every PDFium call is now serialized.
  - **Next.js proxy 30 s timeout**: raised, and SSE keep-alives added.
  - **The OCR orientation classifier garbling a correct line**: turned off, with a regression test.

## Measured (RTX 4060 laptop, **CPU** for OCR/embeddings/reranking; answers by `gemma4:e2b`)

Source: `metrics/phase2_check.json` (run `scripts/phase2_check.py`), `metrics/rag_index.json`, `metrics/rag_search.json`.

| What | Result |
|---|---|
| Demo corpus ingested and indexed (19 docs incl. 5 OCR'd scans → 22 passages) | 53–87 s, depending on other CPU load |
| OCR character accuracy vs ground truth, 5 noisy scans | **95.6%** mean (94.8–96.4%) |
| OCR time per scanned page | ~3–4 s |
| Hindi printed remark (browser-rendered Devanagari) | 96.5% line confidence; all 4 lines correct except one doubled diacritic |
| Grounded QA (4 questions × 3 runs) | **9/12 correct**, **12/12 with valid citations**, **12/12 top source = expected document** |
| Search latency on CPU | ~0.2 s embed + ~5 s rerank (top 8) |
| Median grounded answer, end to end | 8.2 s |

**The 3 wrong answers are all "which CML has the *highest* corrosion rate?".** The 2B model answers C2 (0.300) instead of C3 (0.425), every time, even at temperature 0. The OCR text of that table is correct, and every direct lookup is right (remaining life of C3, the PSV tolerance, the gas re-test interval). This is a small-model reasoning limit. It is the error class the Phase 5 verifier (recomputing numbers in a sandbox) exists to catch, and it should also be re-measured with `qwen3.5:4b` or `qwen3:8b` once downloaded.

## Tests

`make test` → **75 pytest tests** (30 new in Phase 2). They cover:
- **Ingestion** of every file type, with real OCR, deskew and rebuilt rows;
- the cache hit, restart recovery, the no-network OCR guarantee, the vision fallback, and the orientation regression;
- **Retrieval**: chunk offsets and heading cuts, BM25 tokens, RRF math, hybrid search, attachment scoping, removal and re-index;
- **Grounded chat**: SSE sequence, citations, ledger content and the not-ready 409.

The embedder and reranker are tiny deterministic fakes in tests; OCR is real (bundled models).

## Acceptance

> Upload a scanned report, see its OCR text, ask a question about it, get an answer with page-level citations.

**Done** in the browser: the IR-2026-0147 scan was attached in Workbench, then read, indexed and marked ready. The answer "remaining life of 8.5 years [S1] … re-inspect nozzle N3 by UT in 24 months [S1]" was correct. S1 opens page 1 of the scan, where the OCR overlay and text are visible. The call is recorded in the ledger with chunk ids.

## Mocked or limited (see `docs/MOCKS.md`)

- **Reranking on CPU uses the top 8, not 30.** The spec's top-30 needs GPU inference (CUDA PyTorch; see below).
- **Kannada** has no PP-OCR model; it's handled by the vision model only, and labelled.
- **Handwriting** isn't measured on real samples; it gets the vision second opinion only.
- **Qdrant runs embedded** (in-process), including in Docker. Server mode is a config switch, not wired into Compose.

## Needs your decision

- **CUDA PyTorch** (roughly 2.5–3 GB download from download.pytorch.org). It would move the embedder and reranker to the RTX 4060: search would drop from about 5 s to well under a second, and the spec's top-30 rerank would apply. Both models together need about 1.2 GB of VRAM in fp16, alongside the chat model.
- **Docker images are still unbuilt** (Docker Desktop was off). Phase 2 added `libgl1` and model/seed mounts to the API image; building it is the check.

# Mocks, placeholders and known shortcuts

Every item here is either simulated or deliberately incomplete. The UI labels each one where it
appears. Remove an entry only when the real feature ships.

| Item | Where | What's real | What's missing | Replaced in |
|---|---|---|---|---|
| `mock_offline_check` | `scripts/offline_check.py`, `make offline-check` | Checks the API answers locally | Doesn't take the network down or run egress probes. Prints "PLACEHOLDER". | Phase 7 |
| Network isolation card | Sovereignty page | Shows **"Untested"** and makes no claim | Egress self-test (DNS, TCP, HTTPS) | Phase 7 |
| Placeholder pages | Approvals, Router, Eval | Say "not built yet" and which phase builds them | The features themselves | Phases 3–8 |
| Kannada OCR | `config/ingest.yaml` (`kn: rec_model: null`) | Kannada pages go to the local vision model; the UI and warnings say "vision model only" | PP-OCR publishes no Kannada recognition model | If a permissive Kannada OCR model appears |
| CPU reranking depth | `config/rag.yaml` `top_n_cpu: 8` | Real cross-encoder reranking, fewer candidates | Spec's top-30 rerank runs only on GPU (needs CUDA PyTorch) | When CUDA torch is installed |
| Handwriting | Vision second opinion | OCR + vision model on low-confidence pages, disagreement flagged | No dedicated handwriting model; not measured on real handwriting | Phase 8 eval |
| Escalation on this laptop | Router decisions show "escalation blocked" | The cascade decides, records and (when possible) switches to large_text; fully tested against a fake server | `qwen3:8b` isn't downloaded, so no real switch happens here | When the large model is pulled |
| Difficulty signal | `config/router.yaml` difficulty question | Laya is asked; calibration flattens its (near-chance, 37%) answers so they rarely escalate | A usable zero-shot difficulty signal; the spec's optional Laya fine-tune | Optional stretch |
| α (retrieval weight) | `cascade.alpha: 0.5` | Used in every score | Not tuned: needs graded answers with per-request relevance | Phase 8 golden set |
| Vision → text two-stage flow | Router "perception" note | Scans are OCR'd + vision-checked at ingestion; picture tasks are answered by the vision role | A separate VLM perception step feeding a text model | Phase 4 agent |
| vLLM `server` profile | `config/models.yaml` | Declared for completeness | No vLLM service in Compose; only Ollama backends have been exercised | Out of MVP scope unless a 24 GB+ GPU is available |
| Stateless sessions | `kila/auth/security.py` | Signed, expiring, httpOnly cookie | Server-side revocation on logout | If needed |
| Ledger tamper demo | `/ledger/debug/*` | A real raw SQL edit, detected by the real verifier | Deliberately a debug feature; turn off with `ledger.tamper_demo_enabled: false` | By design |

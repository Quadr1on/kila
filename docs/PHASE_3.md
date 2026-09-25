# Phase 3: Laya classifier + cascade router

## Built

- **Laya task classifier** (`kila/router/classifier.py`), loaded from local checkpoints only (`models/laya`: the English and multilingual checkpoints, 1.52 GB).
  - It answers the spec's three typed questions from `config/router.yaml`: `task_type` (8 options), `difficulty`, `needs_vision`.
  - It is warmed in the background at API start (~13 s on CPU), so the first routed message isn't a cold start.
  - **Gating uses the calibrated `answer_confidence`** (max probability). Laya's own docs say its `confidence` field is a normalised entropy that is *not* calibrated and must not be thresholded. The spec's intent (a calibrated confidence, never `act_probability`) is kept; the field name differs. Both values are recorded.
  - `Router(preload=True)` would also fetch the third, typed-decisions checkpoint. We preload only the two we ship, and with `HF_HUB_OFFLINE=1` a missing checkpoint fails instead of going online. That was confirmed when the first attempt was blocked.
- **Labelled set** (`scripts/make_router_labels.py` → `seed/router_labels.jsonl`): **288 synthetic requests**, 36 per task type, 256 English, 16 Hindi and 16 Kannada (hand-written), each labelled with difficulty and vision need.
- **Calibration** (`python -m kila.router.calibrate`):
  - **5-fold cross-validation**, stratified by task, so every request is scored by a temperature fitted without it.
  - A temperature is applied only if cross-validation shows it lowers held-out NLL.
  - τ is picked from a sweep as the least escalation that keeps task accuracy ≥ 95% on requests left on the small model.
  - The temperatures and τ are written into `config/router.yaml`, and the report into `metrics/router_calibration.json`.
  - The first version used a single 70/30 split; its temperature overfit the 88 test rows and *worsened* ECE. It was replaced with CV.
- **Cascade** (`kila/router/cascade.py`):
  - `score = α·task_conf + (1−α)·retrieval_relevance`, or task confidence alone without documents.
  - Code goes to `coder`; picture tasks (P&ID, or the classifier confidently says vision) go to `vision`.
  - A scanned attachment on a text task is recognised as *perception already done at ingestion* (OCR + vision check), so a text model answers.
  - **Escalation** of `small_text` → `large_text` when the score is below τ or the difficulty is confidently high.
  - If the large model isn't downloaded, the decision says **"escalation blocked"** instead of pretending.
  - Every decision is stored as a `tasks` + `router_decisions` row and a `router.decision` ledger event (no request text).
- **Chat:** the model role defaults to **Auto (router)**. The order is retrieve → route (using the real retrieval relevance) → the chosen model streams. Each reply shows an expandable routing line (score maths, reasons, blocked escalation, routing time). Manual roles are still available.
- **Router page:**
  - a routing playground (try any text, pretend attachments, a retrieval-relevance slider; per-question calibrated vs raw probabilities);
  - live stats (routed requests, escalation rate, routing latency, α/τ, share per model and task type);
  - the calibration table, accuracy per language, top confusions, classifier speed, the τ sweep with the chosen row, and recent decisions.

## Measured (CPU, RTX 4060 laptop): `metrics/router_calibration.json`, `metrics/phase3_check.json`

**Calibration**, all 288 requests out-of-fold:

| Question | Accuracy | ECE before → after | Temperature |
|---|---|---|---|
| task_type | **83.0%** | 0.057 → 0.057 | **not applied** (no CV gain; already calibrated) |
| difficulty | 37.1% (chance is 33%) | 0.231 → 0.076 | 3.3 |
| needs_vision | 89.9% | 0.123 → 0.045 | 0.5 |

- Task-type accuracy by language: English **84.4%** (n=256), Hindi **87.5%** (n=16), Kannada **56.3%** (n=16).
- τ = **0.80**: escalates 36% of requests; task accuracy on the rest 95.1%.
- Laya latency: p50 **1.33 s**, p95 1.51 s on CPU (English checkpoint 1.35 s, multilingual 0.48 s). The spec's "~33 ms" is a GPU figure.

**Acceptance run** (20 mixed prompts, real Laya and real retrieval):
- **16/20 task types correct**.
- **8 prompts wanted escalation**: low confidence, or the documents don't cover the question (relevance 0.50 vs 0.72–0.73 when covered).
- **All 8 honestly reported "escalation blocked"**, because `qwen3:8b` isn't downloaded, as agreed.
- Code went to `coder` and P&ID to `vision`.
- Two full auto-routed chats were answered by `gemma4:e2b`, e.g. the PSV test interval, correctly.
- Median routing time **1.17 s**.

## What this means (honest reading)

- **Task type is usable** (83%, well calibrated). Errors cluster: calcs vs code ("PSV sizing" → code), spreadsheet vs approval, and **Kannada**, where the multilingual checkpoint is weak.
- **Zero-shot difficulty is not usable** (37%, near chance). Calibration correctly flattens it, so it rarely triggers escalation. Escalation is driven by the score. The spec's optional stretch, fine-tuning Laya, would be the fix; it's in MOCKS.
- **τ = 0.80 is aggressive** (36% escalation) because the target is 95% accuracy on non-escalated requests. Lower the target (`--target 0.9`) to escalate less.
- **α (0.5) is not tuned**: that needs retrieval relevance per request with graded answers, which is the Phase 8 golden set.
- The labelled set is synthetic and template-based, so the numbers describe this set, not real traffic.

## Tests

`make test` → **91 passed** (16 new in `test_router.py`, plus updated chat/RAG ordering tests). They cover:
- temperature maths;
- temperature fitting recovering a known over-confidence and cutting ECE;
- label-set balance;
- every cascade branch (confident, low score, high difficulty, relevance blending, specialists, scan perception, blocked escalation, classifier unavailable);
- auto-routed chat end to end (the escalated model really answers; decision, task and ledger recorded without text);
- manual override, the API, and stats.

Tests use a deterministic keyword classifier and a pinned copy of `router.yaml`, so recalibrating never changes them.

## Needs your decision

- **`qwen3:8b` (5.2 GB) makes escalation real.** Everything is wired and tested with a fake server. On your laptop, escalation shows as "blocked" until it's downloaded.
- Improving difficulty and Kannada means fine-tuning Laya on a larger labelled set. It's optional in the spec, and I'd do it only if the demo needs it.

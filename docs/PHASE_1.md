# Phase 1: Model plane

## Built

- **`config/models.yaml`**:
  - Profiles `laptop`, `workstation` and `server`, and roles `small_text`, `large_text`, `coder` and `vision`.
  - A catalog of candidate models (Qwen 3/3.5, Qwen2.5-Coder, Qwen3-VL, Gemma 4), all Apache-2.0.
  - Per-call defaults, such as `think: false`.
  - Embedder and reranker paths for Phase 2.
- **`ModelRegistry`** (`kila/models/registry.py`):
  - `get_llm(role)` returns a `ChatOpenAI` pointed at the local server.
  - The YAML is validated and re-read when it changes on disk.
  - Admin activations are stored in the `models` table, take effect on the next request (no restart), and are logged.
- **Health and measurement** (`kila/models/health.py`):
  - Reachability, and which models are downloaded or resident, with VRAM from Ollama `/api/ps`.
  - GPU totals from `nvidia-smi`.
  - A **warm-up** that measures tokens/sec and load time (the swap time), saved to `metrics/model_warmup.json` and logged.
- **Streaming chat** over SSE on the chosen role:
  - Sessions are saved, and each reply keeps its model, token counts, TTFT, tok/s and ledger seq.
  - Every call is logged as `llm.call` with prompt and response hashes (no text).
  - Stop saves the partial reply as `aborted`.
- **Workbench UI:**
  - Chat with a session list and Markdown plus KaTeX math rendering (bundled locally).
  - Stop button, starter prompts, and a per-reply meta line that links to the ledger event.
- **Models UI:**
  - GPU and VRAM bar, resident models, hardware profile notes and backend reachability.
  - Per role: the serving model (admin can pick and activate), its state, measured tok/s, last swap time, and **Warm up**.
- **`scripts/predownload.py`:** a dry run by default that lists every artifact with its real size from the registries. `--yes` pulls the Ollama models and Hugging Face repos. This is the only code allowed online.
- **Compose:** an `ollama` service on the internal network only, with GPU access, `OLLAMA_MAX_LOADED_MODELS=1` and models from `OLLAMA_MODELS_DIR`.

## Measured on this machine (RTX 4060 Laptop, 8 GB)

| Model | Measurement | Value |
|---|---|---|
| gemma4:e2b | cold load (swap) | **6.46 s** |
| gemma4:e2b | generation, warm-up | **90.7–94.7 tok/s** |
| gemma4:e2b | chat reply (433 tokens) | **100.6 tok/s**, first token 0.41 s when resident |
| gemma4:e2b | VRAM when resident | 1.59 GB |

Source: `metrics/model_warmup.json` and the ledger's `llm.call` events.

## Tests

`make test` → **43 pytest tests**. That's 17 new ones: registry defaults and activation, YAML hot reload and validation, fallback when an activated model is removed, the overview, warm-up measurement and the metrics file, SSE streaming, history and system prompt, hot-swap on the next message, the missing-model and unreachable-server errors, and private sessions. They run against an in-process fake Ollama (`tests/mock_llm.py`), so no GPU or network is needed.

## Acceptance

| Check | Status |
|---|---|
| Chat with a local model | Done with the real `gemma4:e2b` on Ollama, in the browser and via curl through the web proxy |
| Swapping `small_text` in the UI takes effect without a restart | Done. Activation is covered by tests and was done live on the real server. A live swap between **two real** models needs a second model downloaded. |
| Works with networking off | Not proven by me. Ollama is local and nothing in the request path goes outside the machine, but I can't switch off your network adapter. Test: turn off Wi-Fi, then chat. |

## Not done yet, or needing you

- **Model downloads.** Only `gemma4:e2b` is on this machine, so the laptop defaults (`qwen3.5:4b` etc.) show "not downloaded". `predownload.py` lists about 16.9 GB for the laptop defaults and about 30 GB for the full catalog plus embedders.
- Docker images are still unbuilt (Docker Desktop is off). The `ollama/ollama:0.34.4` image tag hasn't been pulled or verified.

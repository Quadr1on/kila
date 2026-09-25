# Installing KILA on a new machine

Allow about 30–60 minutes, most of it downloading. The machine needs internet **once**, for
installing tools and downloading models; after that KILA runs fully offline.

Commands are shown for Windows (PowerShell / `scripts/dev.ps1`). On Linux or macOS, use the
matching `make` targets instead (`make setup`, `make predownload ARGS=--yes`, `make dev`).

## What the machine needs

| Item | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11, Linux or macOS | Windows 11 or Linux |
| RAM | 16 GB | 32 GB (the search models use ~5 GB of RAM on CPU) |
| GPU | none (everything also runs on CPU, slowly) | NVIDIA with 8 GB or more VRAM |
| Free disk | ~25 GB | ~50 GB for the full model catalog |

## 1. Install the tools (one time)

1. **Git**: https://git-scm.com
2. **uv** (Python manager; it installs Python 3.11 for you):
   ```
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
3. **Node.js 20 or newer** (LTS): https://nodejs.org
4. **Ollama**: https://ollama.com/download. Start it once and check the tray icon is running.
5. *(Optional)* the **NVIDIA driver**, if the machine has an NVIDIA GPU.

Close and reopen the terminal so the new commands are found.

## 2. Get the code

The repository is `Quadr1on/kila`. If it's private, the new machine's GitHub account needs access.

```
git clone https://github.com/Quadr1on/kila.git
cd kila
```

## 3. Install dependencies

```
powershell -File scripts/dev.ps1 setup
```

This installs Python 3.11 and every Python and web package (~3 GB, mostly PyTorch), and creates
a `.env` file. Then edit `.env`:

- Replace `KILA_SECRET_KEY=change-me` with a random value, which you can generate with:
  ```
  uv run --directory services/api python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- Optionally change `KILA_SEED_PASSWORD`. It's the password for the `engineer`, `reviewer` and
  `admin` accounts, and it's applied only on the very first start (when `data/kila.db` is created).

## 4. Download the models

First see what's missing and how big it is (this downloads nothing):

```
powershell -File scripts/dev.ps1 predownload
```

Then download it:

```
powershell -File scripts/dev.ps1 predownload --yes
```

This fetches:

| What | Size | Where it goes |
|---|---|---|
| Laptop-profile chat models: `qwen3.5:4b`, `qwen3:8b`, `qwen2.5-coder:7b` | ~13 GB | Ollama's model store |
| Search models: bge-m3 (embedder) and bge-reranker-v2-m3 | ~4.6 GB | `models/hf/` |
| Hindi (Devanagari) OCR model, SHA-256 checked | 7.6 MB | `models/ocr/` |
| Laya task classifier for the router (English + multilingual checkpoints) | ~1.5 GB | `models/laya/` |

English OCR models ship inside the `rapidocr` Python package; nothing to download. Add
`--all-catalog` to get every model in `config/models.yaml` (~23 GB of chat models).

**Smaller alternative:** pull only one small multimodal model:

```
ollama pull gemma4:e2b
powershell -File scripts/dev.ps1 predownload --only hf --yes
```

After the first start, sign in as `admin` → **Models** and activate `gemma4:e2b` for
**Small text** and **Vision**.

## 5. Start KILA

```
powershell -File scripts/dev.ps1 dev
```

Open http://localhost:3000 and sign in as `admin`. Then:

1. **Models:** everything should show **reachable**, and the models you downloaded should be
   ready. Click **Warm up** on each to record its speed on this machine.
2. **Knowledge base:** click **Load demo corpus** and wait about a minute while 19 synthetic
   documents are read and indexed.
3. **Workbench:** attach a report from `seed/reports/` and ask about it. The answer should cite
   `[S1]` chips that open the source page.

To confirm the install:

```
uv run --directory services/api pytest
```

Expect every test to pass (91 as of Phase 3). The tests need no models or network.

## 6. (Optional) Take it offline

Turn off Wi-Fi or unplug the network. Chat, OCR, search and the ledger all keep working, because
nothing is fetched at runtime.

## Installing on a machine with no internet at all

1. Do steps 1–4 on a connected machine with the **same OS and CPU architecture**.
2. Copy these to the air-gapped machine:
   - the whole `kila` folder, **including** `services/api/.venv/`, `apps/web/node_modules/` and `models/`;
   - Ollama's model store (Windows: `C:\Users\<you>\.ollama\models`; Linux: `~/.ollama/models`);
   - the uv, Node.js and Ollama installers.
3. On the air-gapped machine, install the three tools, put the Ollama store back in the same
   place, and continue at step 5.

A signed, verified model bundle for this transfer (a one-way import with SHA-256 and signature
checks) is planned for Phase 7.

## Docker (not verified yet)

`docker-compose.yml` defines `api`, `web` and `ollama` on an internal network with no route out.
**It hasn't been built or run yet**, because Docker Desktop was unavailable during development, so
treat this path as unverified. After steps 2–4:

1. Set `OLLAMA_MODELS_DIR` in `.env` to your Ollama model store.
2. Run:
   ```
   docker compose up -d --build
   ```
3. Open http://localhost:3000.

## Common problems

| Symptom | Fix |
|---|---|
| Models page says **unreachable** | Ollama isn't running. Start it from the Start menu (tray) or run `ollama serve`. |
| "Port 3000/8000 is already in use" | KILA is already running in another window. Close it, or run the `Stop-Process` command shown. |
| Chat says a model "isn't downloaded" | `ollama pull <name>`, or activate a model you have on the **Models** page. |
| Knowledge base search says a model is missing | `powershell -File scripts/dev.ps1 predownload --only hf --yes` |
| Forgot the admin password | Stop KILA, delete `data/` (this wipes all local data), set `KILA_SEED_PASSWORD`, start again. |

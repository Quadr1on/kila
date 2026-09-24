# KILA tasks. On Windows without make, use: powershell -File scripts/dev.ps1 <target>
API := services/api
WEB := apps/web
export NEXT_TELEMETRY_DISABLED := 1

.PHONY: setup dev dev-api dev-web test typecheck audit build up down offline-check seed

setup:            ## install deps (the only step that needs the network)
	uv sync --directory $(API) --python 3.11
	npm --prefix $(WEB) ci
	@test -f .env || (cp .env.example .env && echo "created .env; set KILA_SECRET_KEY")

dev:              ## api on :8000 + web on :3000 (web proxies /api -> api)
	$(MAKE) -j2 dev-api dev-web

dev-api:
	uv run --directory $(API) uvicorn kila.main:app --host 127.0.0.1 --port 8000 --reload

dev-web:
	npm --prefix $(WEB) run dev

test:
	uv run --directory $(API) pytest
	npm --prefix $(WEB) run typecheck

audit:            ## licence audit, fails on AGPL/GPL/SSPL/...
	uv run --directory $(API) python ../../scripts/licence_audit.py

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

seed:
	uv run --directory $(API) python -m kila.seed

offline-check:    ## Phase 7 makes this real (see docs/MOCKS.md)
	uv run --directory $(API) python ../../scripts/offline_check.py

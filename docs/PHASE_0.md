# Phase 0: Foundations

## Built

- **Monorepo scaffold** following spec §3. `docker-compose.yml` has an `internal: true` network (see ARCHITECTURE.md, "Isolation boundary"). Also `.env.example`, a `Makefile`, and `scripts/dev.ps1` as the Windows equivalent.
- **SQLite + SQLModel + Alembic** for all 14 tables in §4, plus `objects.deleted_at`. Migration `0001_initial`, WAL mode, and migrate + seed on startup.
- **Hash-chained ledger** with append, verify, event listing and filtering, a head endpoint, the admin tamper/restore demo and an ed25519-signed export.
- **KILA Local Bucket** with content-addressed dedup, upload/list/download/meta, HMAC signed URLs, soft delete, per-bucket role checks, and image/PDF thumbnails. A Supabase-like TS client lives in `apps/web/lib/storage.ts`.
- **Local auth**: bcrypt, an httpOnly signed cookie, `require_role`, and three seeded users (`engineer`, `reviewer`, `admin`).
- **Next.js shell**:
  - login, sidebar, and an engineering-drawing title block on every page;
  - a working **Files** page (tabs per bucket, drag-and-drop upload, thumbnails, preview for images/PDF/text, SHA-256, a per-file audit trail);
  - a working **Sovereignty** page (ledger table, Verify chain, tamper demo, signed export);
  - labelled placeholders for Workbench, Knowledge base, Approvals, Models, Router and Eval.
- **Licence audit** (`scripts/licence_audit.py`): 0 denied licences, 5 documented exceptions.

## Tests

`make test` → **26 pytest tests** (ledger chaining, tamper, deleted-row and forged-hash detection, concurrent
appends, signed export, dedup, soft delete, thumbnails, signed-URL expiry, role checks, unsafe-MIME
handling, auth) plus `tsc --noEmit`. They run offline and take about 20 s.

## Acceptance check (done in the browser, Sept 25 2026)

1. Signed in as `engineer`, then uploaded a synthetic scanned inspection report (PNG) and a CSV on the Files page.
2. Preview rendered. The file's audit trail showed `storage.upload` and `storage.read` with its sha256.
3. As `admin` on Sovereignty, **Verify chain** reported "Intact, all 11 entries".
4. **Edit row #6** changed that row in SQLite, and verify then reported "Broken at #6 (hash mismatch)" with the row highlighted.
5. **Restore** put the row back, and verify reported "Intact" again.

## Mocked or deferred

See `docs/MOCKS.md`: the offline-check placeholder and the "Untested" isolation card (both Phase 7), plus the placeholder pages.

## Not verified yet

- **Docker images haven't been built.** Docker Desktop wasn't running during Phase 0. `docker compose config` validates. Run `make build && make up`, or `scripts/dev.ps1 build`, then `up`.

## Run

```
make setup          # or: powershell -File scripts/dev.ps1 setup
make dev            # api :8000, web :3000 → http://localhost:3000  (engineer / kila-demo)
make test
make audit
```

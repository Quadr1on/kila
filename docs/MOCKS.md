# Mocks, placeholders and known shortcuts

Every item here is either simulated or deliberately incomplete. The UI labels each one where it
appears. Remove an entry only when the real feature ships.

| Item | Where | What's real | What's missing | Replaced in |
|---|---|---|---|---|
| `mock_offline_check` | `scripts/offline_check.py`, `make offline-check` | Checks the API answers locally | Doesn't take the network down or run egress probes. Prints "PLACEHOLDER". | Phase 7 |
| Network isolation card | Sovereignty page | Shows **"Untested"** and makes no claim | Egress self-test (DNS, TCP, HTTPS) | Phase 7 |
| Placeholder pages | Workbench, Knowledge base, Approvals, Models, Router, Eval | Say "not built yet" and which phase builds them | The features themselves | Phases 1–8 |
| Stateless sessions | `kila/auth/security.py` | Signed, expiring, httpOnly cookie | Server-side revocation on logout | If needed |
| Ledger tamper demo | `/ledger/debug/*` | A real raw SQL edit, detected by the real verifier | Deliberately a debug feature; turn off with `ledger.tamper_demo_enabled: false` | By design |

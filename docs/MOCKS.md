# Mocks, placeholders and known shortcuts

Every item here is either simulated or deliberately incomplete. The UI labels each one where it
appears. Remove an entry only when the real feature ships.

| Item | Where | What's real | What's missing | Replaced in |
|---|---|---|---|---|
| `mock_offline_check` | `scripts/offline_check.py`, `make offline-check` | Checks the API answers locally | Doesn't take the network down or run egress probes. Prints "PLACEHOLDER". | Phase 7 |
| Network isolation card | Sovereignty page | Shows **"Untested"** and makes no claim | Egress self-test (DNS, TCP, HTTPS) | Phase 7 |
| Placeholder pages | Knowledge base, Approvals, Router, Eval | Say "not built yet" and which phase builds them | The features themselves | Phases 2–8 |
| Manual model-role picker | Workbench chat header | Really switches which role, and so which model, answers | Automatic routing by Laya + the cascade | Phase 3 |
| vLLM `server` profile | `config/models.yaml` | Declared for completeness | No vLLM service in Compose; only Ollama backends have been exercised | Out of MVP scope unless a 24 GB+ GPU is available |
| Stateless sessions | `kila/auth/security.py` | Signed, expiring, httpOnly cookie | Server-side revocation on logout | If needed |
| Ledger tamper demo | `/ledger/debug/*` | A real raw SQL edit, detected by the real verifier | Deliberately a debug feature; turn off with `ledger.tamper_demo_enabled: false` | By design |

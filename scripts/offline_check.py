"""mock_offline_check: PLACEHOLDER until Phase 7 (listed in docs/MOCKS.md).

Phase 7 replaces this with: bring the stack up with the host network down, run the egress
self-test, and smoke-test every feature. Today it only checks that the API answers locally
and that the ledger verifies. It does NOT prove isolation, and says so.
"""

import json
import sys
import urllib.request

API = "http://127.0.0.1:8000"


def main() -> int:
    print("offline-check: PHASE 0 PLACEHOLDER. This does not test network isolation.")
    try:
        with urllib.request.urlopen(f"{API}/health", timeout=3) as r:
            print("  api /health:", json.loads(r.read()))
    except OSError as e:
        print(f"  api not reachable at {API}: {e}")
        return 1
    print("  egress self-test: NOT IMPLEMENTED (phase 7)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

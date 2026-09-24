# infra

Placeholder. Phase 7 adds:

- `nftables.conf`: a Linux host policy with default-DROP output except loopback and the Docker
  bridges, plus install instructions.
- `tetragon/`: a TracingPolicy for `connect()`/`sendto()` from KILA containers (stretch goal).

Neither runs on the current Windows dev host (Docker Desktop + WSL2), and the UI will not claim
either one unless it is deployed. The Compose network layout is in `/docker-compose.yml` and
explained in `docs/ARCHITECTURE.md`.

"""Fetch every model KILA needs, ONCE, while the machine is online (spec §7.3).

After this, the stack runs with networking off. By default this is a DRY RUN that lists what
would be downloaded and how big it is. Nothing is fetched without --yes.

    uv run --directory services/api --group setup python ../../scripts/predownload.py            # plan only
    uv run --directory services/api --group setup python ../../scripts/predownload.py --yes      # download
    ... --all-catalog     include every catalog model, not just the active profile's defaults
    ... --only ollama     just the Ollama models (or: hf)

Ollama models are pulled into whatever Ollama server KILA_OLLAMA_URL points at (default: local).
Hugging Face repos go to models/hf/<name> and are later loaded from that path with
HF_HUB_OFFLINE=1. Laya (phase 3) and PaddleOCR (phase 2) are added here when those phases land.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "https://registry.ollama.ai/v2/library"
_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def expand(s: str) -> str:
    return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), s)


def gb(n: int | None) -> str:
    return "?" if not n else f"{n / 1e9:.2f} GB"


def plan(cfg: dict, all_catalog: bool) -> tuple[list[str], list[dict]]:
    profile = os.environ.get("KILA_MODEL_PROFILE") or cfg["active_profile"]
    if all_catalog:
        ollama = [m["name"] for m in cfg["catalog"] if cfg["backends"][m["backend"]].get("kind") == "ollama"]
    else:
        ollama = [r["default"] for r in cfg["profiles"][profile]["roles"].values()]
    ollama = sorted(set(ollama))
    hf = [{"role": role, **spec} for role, spec in (cfg.get("local_models") or {}).items()]
    return ollama, hf


def ollama_size(client: httpx.Client, name: str) -> int | None:
    repo, _, tag = name.partition(":")
    try:
        r = client.get(f"{REGISTRY}/{repo}/manifests/{tag or 'latest'}",
                       headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
        r.raise_for_status()
        m = r.json()
        return sum(layer.get("size", 0) for layer in m.get("layers", [])) + m.get("config", {}).get("size", 0)
    except httpx.HTTPError:
        return None


def hf_size(client: httpx.Client, repo: str) -> int | None:
    try:
        r = client.get(f"https://huggingface.co/api/models/{repo}", params={"blobs": "true"})
        r.raise_for_status()
        return sum(s.get("size") or 0 for s in r.json().get("siblings", []))
    except httpx.HTTPError:
        return None


def pull_ollama(base: str, name: str) -> None:
    last = ""
    with httpx.Client(timeout=httpx.Timeout(10, read=None)) as c, \
            c.stream("POST", f"{base}/api/pull", json={"model": name, "stream": True}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if "error" in d:
                raise RuntimeError(d["error"])
            status = d.get("status", "")
            if d.get("total"):
                status += f" {d.get('completed', 0) * 100 // d['total']}%"
            if status != last:
                print(f"    {name}: {status}", end="\r", flush=True)
                last = status
    print(f"    {name}: done{' ' * 40}")


def pull_hf(repo: str, dest: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("huggingface_hub is missing: run with `uv run --group setup ...`")
    os.environ.pop("HF_HUB_OFFLINE", None)  # this script is the one place allowed online
    snapshot_download(repo_id=repo, local_dir=str(dest))
    print(f"    {repo} -> {dest.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--yes", action="store_true", help="actually download (default: dry run)")
    ap.add_argument("--all-catalog", action="store_true", help="every catalog model, not only profile defaults")
    ap.add_argument("--only", choices=["ollama", "hf"])
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    base = expand(cfg["backends"]["ollama"]["base_url"])
    ollama, hf = plan(cfg, args.all_catalog)
    if args.only == "hf":
        ollama = []
    if args.only == "ollama":
        hf = []

    try:
        with httpx.Client(timeout=5) as c:
            have = {m["name"] for m in c.get(f"{base}/api/tags").json().get("models", [])}
    except httpx.HTTPError:
        sys.exit(f"Ollama isn't reachable at {base}. Start it first (or set KILA_OLLAMA_URL).")

    print(f"Profile: {os.environ.get('KILA_MODEL_PROFILE') or cfg['active_profile']}   Ollama: {base}\n")
    todo_o, todo_h, total = [], [], 0
    with httpx.Client(timeout=15, follow_redirects=True) as c:
        print("Ollama models")
        for name in ollama:
            if name in have:
                print(f"  [have] {name}")
                continue
            size = ollama_size(c, name)
            total += size or 0
            todo_o.append(name)
            print(f"  [get ] {name:22} {gb(size):>9}   source: {REGISTRY}/{name.split(':')[0]}")
        print("\nHugging Face models")
        for m in hf:
            dest = ROOT / m["path"]
            if dest.exists() and any(dest.iterdir()):
                print(f"  [have] {m['hf_repo']}  ({m['path']})")
                continue
            size = hf_size(c, m["hf_repo"])
            total += size or 0
            todo_h.append(m)
            print(f"  [get ] {m['hf_repo']:28} {gb(size):>9}   licence {m.get('licence')}  -> {m['path']}")

    print(f"\nTo download: {len(todo_o) + len(todo_h)} item(s), about {gb(total)}")
    if not args.yes:
        print("Dry run only. Re-run with --yes to download.")
        return 0

    for name in todo_o:
        pull_ollama(base, name)
    for m in todo_h:
        pull_hf(m["hf_repo"], ROOT / m["path"])
    print("\nDone. KILA can now run with networking off.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Licence audit for Python (installed env) and npm (apps/web/node_modules) dependencies.

Fails (exit 1) on strong copyleft / non-commercial licences. Weak copyleft and unknowns
are reported as warnings unless explicitly accepted in EXCEPTIONS (with a reason that
must also appear in docs/LICENSES.md).

Run from the API venv so Python packages are visible:
    uv run --directory services/api python ../../scripts/licence_audit.py
"""

from __future__ import annotations

import json
import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DENY = re.compile(r"\b(AGPL|GPL|SSPL|BUSL|Commons[- ]Clause|CC-BY-NC|Elastic)\b", re.I)
WEAK = re.compile(r"\b(LGPL|MPL|EPL|CDDL)\b", re.I)
PERMISSIVE = re.compile(
    r"\b(MIT|MIT-0|MIT-CMU|Apache|BSD|ISC|0BSD|Zlib|Unlicense|CC0|Python-2\.0|PSF|HPND|BlueOak|CC-BY-4\.0|OFL|Unicode|WTFPL)\b",
    re.I,
)

# name -> reason. Keep in sync with docs/LICENSES.md.
EXCEPTIONS: dict[str, str] = {
    "certifi": "MPL-2.0 CA bundle (data file, unmodified). Pulled in by httpx (dev/test only).",
    "@img/sharp-libvips-win32-x64": "LGPL-3.0 libvips, dynamically loaded by sharp for next/image. KILA does not use next/image.",
    "@img/sharp-libvips-linux-x64": "LGPL-3.0 libvips, dynamically loaded by sharp for next/image. KILA does not use next/image.",
    "@img/sharp-libvips-linuxmusl-x64": "LGPL-3.0 libvips, dynamically loaded by sharp for next/image. KILA does not use next/image.",
    "@img/sharp-win32-x64": "Apache-2.0 AND LGPL-3.0 (bundles libvips). Same reason as sharp-libvips.",
    "@img/sharp-wasm32": "Apache-2.0 AND LGPL-3.0 (bundles libvips). Same reason as sharp-libvips.",
    "lightningcss": "MPL-2.0 CSS compiler used by Tailwind at build time only; not shipped in the runtime image.",
    "lightningcss-win32-x64-msvc": "MPL-2.0 native binary of lightningcss; build time only.",
    "lightningcss-linux-x64-gnu": "MPL-2.0 native binary of lightningcss; build time only.",
    "lightningcss-linux-x64-musl": "MPL-2.0 native binary of lightningcss; build time only.",
}
SELF = {"kila", "kila-web"}


def classify(lic: str) -> str:
    if not lic or lic.upper() in {"UNKNOWN", "SEE LICENSE IN LICENSE", "NONE"}:
        return "unknown"
    # "LGPL" contains "GPL": check weak copyleft first, then strong.
    stripped = WEAK.sub("", lic)
    if DENY.search(stripped):
        # Dual licences like "(MIT OR GPL-3.0)" are fine if a permissive option exists.
        if " OR " in lic.upper() and PERMISSIVE.search(lic):
            return "ok"
        return "deny"
    if WEAK.search(lic):
        if " OR " in lic.upper() and PERMISSIVE.search(lic):
            return "ok"
        return "weak"
    return "ok" if PERMISSIVE.search(lic) else "unknown"


def python_licences() -> list[dict]:
    out = []
    for dist in metadata.distributions():
        md = dist.metadata
        lic = md.get("License-Expression") or ""
        if not lic:
            classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
            lic = "; ".join(classifiers)
        if not lic:
            first_line = (md.get("License") or "").strip().splitlines()
            lic = first_line[0][:80] if first_line else ""
        out.append({"eco": "python", "name": md.get("Name") or "?", "version": md.get("Version"),
                    "license": lic or "UNKNOWN"})
    return out


def _is_package_root(pj: Path) -> bool:
    """True for .../node_modules/<pkg>/package.json and .../node_modules/@scope/<pkg>/package.json."""
    parent = pj.parent
    if parent.parent.name == "node_modules":
        return not parent.name.startswith("@")
    return parent.parent.name.startswith("@") and parent.parent.parent.name == "node_modules"


def npm_licences() -> list[dict]:
    nm = ROOT / "apps" / "web" / "node_modules"
    found: dict[tuple[str, str], dict] = {}
    for pj in nm.rglob("package.json") if nm.exists() else []:
        if not _is_package_root(pj):
            continue
        try:
            data = json.loads(pj.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if "name" not in data or "version" not in data:
            continue
        lic = data.get("license")
        if isinstance(lic, dict):
            lic = lic.get("type")
        if not lic and isinstance(data.get("licenses"), list):
            lic = " OR ".join(x.get("type", "") for x in data["licenses"] if isinstance(x, dict))
        found[(data["name"], data["version"])] = {"eco": "npm", "name": data["name"], "version": data["version"],
                                                   "license": lic or "UNKNOWN"}
    return list(found.values())


def main() -> int:
    rows = python_licences() + npm_licences()
    report: dict[str, list[dict]] = {"deny": [], "weak": [], "unknown": [], "excepted": [], "ok": []}
    for r in rows:
        if r["name"] in SELF:
            continue
        status = classify(r["license"])
        if status != "ok" and r["name"] in EXCEPTIONS:
            r["reason"] = EXCEPTIONS[r["name"]]
            status = "excepted"
        report[status].append(r)

    out = ROOT / "metrics" / "licence_audit.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({k: sorted(v, key=lambda x: x["name"]) for k, v in report.items()}, indent=2),
                   encoding="utf-8")

    print(f"Checked {len(rows)} packages  ok={len(report['ok'])}  excepted={len(report['excepted'])}  "
          f"weak={len(report['weak'])}  unknown={len(report['unknown'])}  DENY={len(report['deny'])}")
    for k in ("deny", "weak", "unknown", "excepted"):
        for r in report[k]:
            print(f"  [{k:8}] {r['eco']:6} {r['name']}@{r['version']}: {r['license']}")
    print(f"Report: {out.relative_to(ROOT)}")
    return 1 if report["deny"] else 0


if __name__ == "__main__":
    sys.exit(main())

"""Model registry: role -> model spec -> LLM client.

Sources, in priority order:
  1. an admin activation stored in the `models` table (active=True for profile+role)
  2. the profile's `default` in config/models.yaml
The YAML is re-read whenever its mtime changes, so edits take effect without a restart.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session, select

from kila import ledger
from kila.db.models import ModelEntry
from kila.db.session import get_engine
from kila.settings import get_settings

ROLES = ("small_text", "large_text", "coder", "vision")
_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass(frozen=True)
class Backend:
    name: str
    kind: str  # "ollama" | "openai"
    base_url: str  # native root (no /v1)

    @property
    def openai_base(self) -> str:
        return self.base_url.rstrip("/") + "/v1"


@dataclass(frozen=True)
class ModelSpec:
    role: str
    name: str
    backend: Backend
    source: str  # "activation" | "default"
    licence: str | None = None
    note: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


class RegistryError(Exception):
    pass


class ModelRegistry:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._cfg: dict[str, Any] = {}

    # ------------------------------------------------------------ config

    def config(self) -> dict[str, Any]:
        """Current YAML (reloaded if the file changed on disk)."""
        mtime = self.path.stat().st_mtime
        if mtime != self._mtime:
            with self._lock:
                if mtime != self._mtime:
                    with open(self.path, encoding="utf-8") as f:
                        cfg = _expand_env(yaml.safe_load(f))
                    self._validate(cfg)
                    first_load = self._mtime is None
                    self._cfg, self._mtime = cfg, mtime
                    self._sync_catalog()
                    if not first_load:
                        ledger.append("system", "model.config_reloaded", {"path": self.path.name})
        return self._cfg

    @property
    def profile(self) -> str:
        return os.environ.get("KILA_MODEL_PROFILE") or self.config()["active_profile"]

    def _validate(self, cfg: dict[str, Any]) -> None:
        names = {m["name"] for m in cfg.get("catalog", [])}
        for pname, p in cfg["profiles"].items():
            for role, r in p["roles"].items():
                if role not in ROLES:
                    raise RegistryError(f"profile {pname}: unknown role {role}")
                if r["default"] not in names:
                    raise RegistryError(f"profile {pname}/{role}: default {r['default']} not in catalog")
        for m in cfg.get("catalog", []):
            if m["backend"] not in cfg["backends"]:
                raise RegistryError(f"catalog {m['name']}: unknown backend {m['backend']}")

    def backend(self, name: str) -> Backend:
        b = self.config()["backends"][name]
        return Backend(name=name, kind=b.get("kind", "openai"), base_url=b["base_url"])

    def catalog_entry(self, name: str) -> dict[str, Any] | None:
        return next((m for m in self.config().get("catalog", []) if m["name"] == name), None)

    def candidates(self, role: str) -> list[dict[str, Any]]:
        return [m for m in self.config().get("catalog", []) if role in m.get("roles", [])]

    # ------------------------------------------------------------ DB activations

    def sync(self) -> None:
        """Load/validate the YAML and mirror its catalog into the DB. Called on API startup."""
        self.config()
        self._sync_catalog()

    def _sync_catalog(self) -> None:
        """Mirror catalog x roles into the `models` table for every profile (idempotent)."""
        cfg = self._cfg
        with Session(get_engine()) as s:
            rows = s.exec(select(ModelEntry)).all()
            have = {(r.profile, r.role, r.name) for r in rows}
            for pname in cfg["profiles"]:
                for m in cfg.get("catalog", []):
                    for role in m.get("roles", []):
                        if (pname, role, m["name"]) not in have:
                            s.add(ModelEntry(name=m["name"], role=role, backend=m["backend"],
                                             endpoint=cfg["backends"][m["backend"]]["base_url"],
                                             profile=pname, active=False))
            s.commit()

    def _activation(self, role: str) -> str | None:
        with Session(get_engine()) as s:
            row = s.exec(select(ModelEntry).where(ModelEntry.profile == self.profile, ModelEntry.role == role,
                                                  ModelEntry.active == True)).first()  # noqa: E712
            return row.name if row else None

    def spec(self, role: str) -> ModelSpec:
        cfg = self.config()
        prof = cfg["profiles"][self.profile]
        if role not in prof["roles"]:
            raise RegistryError(f"role {role} not configured for profile {self.profile}")
        name, source = self._activation(role), "activation"
        entry = self.catalog_entry(name) if name else None
        if entry is None or role not in entry.get("roles", []):
            # No activation, or the activated model was removed from the YAML: use the default.
            name, source = prof["roles"][role]["default"], "default"
            entry = self.catalog_entry(name)
        assert entry is not None
        params = {**cfg.get("defaults", {}), **prof["roles"][role].get("params", {})}
        return ModelSpec(role=role, name=name, backend=self.backend(entry["backend"]), source=source,
                         licence=entry.get("licence"), note=entry.get("note"), params=params)

    def activate(self, role: str, name: str, actor: str) -> ModelSpec:
        entry = self.catalog_entry(name)
        if entry is None or role not in entry.get("roles", []):
            raise RegistryError(f"{name} is not a catalog candidate for {role}")
        before = self.spec(role).name
        with Session(get_engine()) as s:
            rows = s.exec(select(ModelEntry).where(ModelEntry.profile == self.profile,
                                                   ModelEntry.role == role)).all()
            if not any(r.name == name for r in rows):
                rows.append(ModelEntry(name=name, role=role, backend=entry["backend"], profile=self.profile,
                                       endpoint=self.backend(entry["backend"]).base_url))
            for row in rows:
                row.active = row.name == name
                s.add(row)
            s.commit()
        after = self.spec(role)
        ledger.append(actor, "model.activate", {"profile": self.profile, "role": role, "from": before,
                                                "to": after.name, "backend": after.backend.name})
        return after

    # ------------------------------------------------------------ clients

    def get_llm(self, role: str, **overrides: Any):
        """LangChain ChatOpenAI for this role, pointed at the local OpenAI-compatible server."""
        from langchain_openai import ChatOpenAI  # heavy import; keep it lazy

        spec = self.spec(role)
        p = {**spec.params, **overrides}
        extra: dict[str, Any] = {}
        if spec.backend.kind == "ollama":
            if p.get("think") is False:
                extra["reasoning_effort"] = "none"
            if p.get("keep_alive"):
                extra["keep_alive"] = p["keep_alive"]
        return ChatOpenAI(
            model=spec.name,
            base_url=spec.backend.openai_base,
            api_key="local-no-key",  # local servers ignore it; the client requires a value
            temperature=p.get("temperature", 0.3),
            max_tokens=p.get("max_tokens", 1024),
            streaming=True,
            stream_usage=True,
            max_retries=0,
            timeout=300,
            extra_body=extra or None,
        )


_registry: ModelRegistry | None = None


def reset_registry() -> None:
    """Forget the cached registry (tests switch config dirs / env)."""
    global _registry
    _registry = None


def get_registry() -> ModelRegistry:
    global _registry
    path = get_settings().config_dir / "models.yaml"
    if _registry is None or _registry.path != path:
        _registry = ModelRegistry(path)
    return _registry


def get_llm(role: str, **overrides: Any):
    return get_registry().get_llm(role, **overrides)

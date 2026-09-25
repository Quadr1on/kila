"""Runtime settings: env vars (KILA_*) for paths/secrets, config/app.yaml for behaviour."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

# Where models/, seed/, config/ live. In the repo: three levels above this file. In the Docker
# image the package sits at /app/kila, so the image sets KILA_ROOT=/app.
REPO_ROOT = Path(os.environ["KILA_ROOT"]) if os.environ.get("KILA_ROOT") else Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KILA_", env_file=".env", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    config_dir: Path = REPO_ROOT / "config"
    metrics_dir: Path = REPO_ROOT / "metrics"
    # Used for HMAC signed URLs and session cookies. MUST be overridden outside dev.
    secret_key: str = "dev-insecure-change-me"
    seed_password: str = "kila-demo"
    cookie_secure: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kila.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def buckets_dir(self) -> Path:
        return self.data_dir / "buckets"

    @property
    def keys_dir(self) -> Path:
        return self.data_dir / "keys"

    @property
    def app(self) -> dict[str, Any]:
        return load_app_config(self.config_dir)


@lru_cache
def load_app_config(config_dir: Path) -> dict[str, Any]:
    with open(config_dir / "app.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s

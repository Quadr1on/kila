from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PASSWORD = "test-pass"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    """Fresh data dir + DB per test. Migrations and seed run exactly as in production."""
    monkeypatch.setenv("KILA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KILA_SEED_PASSWORD", PASSWORD)
    monkeypatch.setenv("KILA_SECRET_KEY", "test-secret")
    from kila.db.session import reset_engine
    from kila.settings import get_settings

    get_settings.cache_clear()
    reset_engine()
    from kila.main import app

    with TestClient(app) as c:  # runs lifespan: migrate + seed + startup event
        yield app, c
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture()
def client_for(app_env):
    app, _ = app_env
    made: list[TestClient] = []

    def _login(username: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/auth/login", json={"username": username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        made.append(c)
        return c

    yield _login
    for c in made:
        c.close()

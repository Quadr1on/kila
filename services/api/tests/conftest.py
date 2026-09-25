from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PASSWORD = "test-pass"


@pytest.fixture(scope="session")
def mock_llm():
    from tests.mock_llm import MockLLMServer

    with MockLLMServer() as srv:
        yield srv


@pytest.fixture()
def app_env(tmp_path, monkeypatch, mock_llm):
    """Fresh data dir + DB per test. Migrations and seed run exactly as in production.
    The model backend points at an in-process fake Ollama, so nothing touches a real model."""
    monkeypatch.setenv("KILA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KILA_METRICS_DIR", str(tmp_path / "metrics"))
    monkeypatch.setenv("KILA_SEED_PASSWORD", PASSWORD)
    monkeypatch.setenv("KILA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("KILA_OLLAMA_URL", mock_llm.url)
    monkeypatch.delenv("KILA_MODEL_PROFILE", raising=False)
    from kila.db.session import reset_engine
    from kila.models.registry import reset_registry
    from kila.rag import models as rag_models
    from kila.rag.store import reset_store
    from kila.settings import get_settings, load_app_config
    from tests.fakes import HashEmbedder, OverlapReranker

    get_settings.cache_clear()
    load_app_config.cache_clear()
    reset_engine()
    reset_registry()
    reset_store()
    rag_models.set_embedder(HashEmbedder())
    rag_models.set_reranker(OverlapReranker())
    from kila.main import app

    with TestClient(app) as c:  # runs lifespan: migrate + seed + startup event
        yield app, c
    reset_store()
    rag_models.set_embedder(None)
    rag_models.set_reranker(None)
    reset_engine()
    reset_registry()
    get_settings.cache_clear()
    load_app_config.cache_clear()


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

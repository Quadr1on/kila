from __future__ import annotations

import json
import os
import shutil
import time

import pytest

from kila.models.registry import ModelRegistry, RegistryError, get_registry


def test_default_spec_and_llm_client(app_env, mock_llm):
    reg = get_registry()
    spec = reg.spec("small_text")
    assert spec.name == "qwen3.5:4b" and spec.source == "default"
    assert spec.backend.base_url == mock_llm.url  # ${KILA_OLLAMA_URL:-...} expanded
    llm = reg.get_llm("small_text")
    assert llm.model_name == "qwen3.5:4b"
    assert str(llm.openai_api_base).rstrip("/") == f"{mock_llm.url}/v1"
    assert llm.extra_body["reasoning_effort"] == "none"  # think: false


def test_activation_overrides_default_and_is_logged(client_for):
    admin = client_for("admin")
    r = admin.post("/models/small_text/activate", json={"name": "gemma4:e2b"})
    assert r.status_code == 200 and r.json()["source"] == "activation"
    assert get_registry().spec("small_text").name == "gemma4:e2b"
    ev = admin.get("/ledger/events?event_type=model.activate").json()[0]["payload"]
    assert ev == {"profile": "laptop", "role": "small_text", "from": "qwen3.5:4b", "to": "gemma4:e2b",
                  "backend": "ollama"}
    # other roles untouched
    assert get_registry().spec("vision").name == "qwen3.5:4b"


def test_activation_rejects_non_candidates_and_non_admins(client_for):
    admin = client_for("admin")
    assert admin.post("/models/small_text/activate", json={"name": "qwen2.5-coder:7b"}).status_code == 400
    assert admin.post("/models/small_text/activate", json={"name": "made-up:1b"}).status_code == 400
    assert admin.post("/models/nope/activate", json={"name": "gemma4:e2b"}).status_code == 404
    assert client_for("engineer").post("/models/small_text/activate", json={"name": "gemma4:e2b"}).status_code == 403


def test_yaml_hot_reload(tmp_path, app_env, monkeypatch):
    from kila.settings import REPO_ROOT

    cfg_dir = tmp_path / "cfg"
    shutil.copytree(REPO_ROOT / "config", cfg_dir)
    reg = ModelRegistry(cfg_dir / "models.yaml")
    assert reg.spec("large_text").name == "qwen3:8b"

    path = cfg_dir / "models.yaml"
    text = path.read_text(encoding="utf-8").replace(
        'large_text: { default: "qwen3:8b" }', 'large_text: { default: "qwen3.5:9b" }', 1)
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))  # make sure the mtime visibly changes
    assert reg.spec("large_text").name == "qwen3.5:9b"


def test_yaml_validation(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(
        "active_profile: laptop\nbackends: {ollama: {base_url: 'http://x'}}\n"
        "catalog: [{name: a, backend: ollama, roles: [small_text]}]\n"
        "profiles: {laptop: {roles: {small_text: {default: missing}}}}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="not in catalog"):
        ModelRegistry(p).config()


def test_removed_activation_falls_back_to_default(app_env):
    from sqlmodel import Session

    from kila.db.models import ModelEntry
    from kila.db.session import get_engine

    reg = get_registry()
    with Session(get_engine()) as s:  # an activation for a model no longer in the YAML catalog
        s.add(ModelEntry(name="retired:1b", role="small_text", backend="ollama", profile="laptop", active=True))
        s.commit()
    assert reg.spec("small_text").name == "qwen3.5:4b"


def test_overview_reports_pulled_and_candidates(client_for):
    data = client_for("engineer").get("/models").json()
    assert data["profile"] == "laptop"
    roles = {r["role"]: r for r in data["roles"]}
    assert roles["small_text"]["pulled"] is True
    assert roles["coder"]["pulled"] is False  # qwen2.5-coder isn't on the fake server
    assert {c["name"] for c in roles["small_text"]["candidates"]} >= {"qwen3.5:4b", "gemma4:e2b"}
    assert data["backends"]["ollama"]["reachable"] is True


def test_warmup_measures_and_records(client_for, tmp_path):
    eng = client_for("engineer")
    first = eng.post("/models/large_text/warmup").json()
    assert first["model"] == "qwen3:8b" and first["tok_s"] == 50.0
    assert first["was_resident"] is False and first["load_ms"] == 2000.0  # measured swap
    second = eng.post("/models/large_text/warmup").json()
    assert second["was_resident"] is True and second["load_ms"] < 10

    runs = json.loads((tmp_path / "metrics" / "model_warmup.json").read_text())
    assert [r["model"] for r in runs[-2:]] == ["qwen3:8b", "qwen3:8b"]
    view = {r["role"]: r for r in eng.get("/models").json()["roles"]}["large_text"]
    assert view["warmup"]["last_cold"]["load_ms"] == 2000.0
    assert eng.get("/ledger/events?event_type=model.warmup").json()[0]["payload"]["tok_s"] == 50.0


def test_warmup_missing_model_is_502(client_for):
    assert client_for("engineer").post("/models/coder/warmup").status_code == 502


def test_reviewer_cannot_warm_up(client_for):
    assert client_for("reviewer").post("/models/small_text/warmup").status_code == 403


def test_registry_reload_is_cheap_when_unchanged(app_env):
    reg = get_registry()
    reg.config()
    t0 = time.perf_counter()
    for _ in range(200):
        reg.config()
    assert time.perf_counter() - t0 < 0.5

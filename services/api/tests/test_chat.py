from __future__ import annotations

import hashlib
import json


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def _chat(c, content, role="small_text"):
    sid = c.post("/chat/sessions", json={}).json()["id"]
    r = c.post(f"/chat/sessions/{sid}/messages", json={"content": content, "role": role})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return sid, _events(r.text)


def test_streaming_reply_is_saved_and_ledgered(client_for):
    eng = client_for("engineer")
    sid, evs = _chat(eng, "What is a PSV?")
    kinds = [k for k, _ in evs]
    assert kinds[0] == "start" and kinds[-1] == "done" and kinds.count("delta") == 4
    assert evs[0][1]["model"] == "qwen3.5:4b"
    reply = "".join(d["text"] for k, d in evs if k == "delta")
    assert reply == "Answer from qwen3.5:4b."

    done = evs[-1][1]
    assert done["output_tokens"] == 4 and done["input_tokens"] == 30 and done["status"] == "ok"
    assert done["ttft_ms"] is not None and done["ledger_seq"] > 0

    msgs = eng.get(f"/chat/sessions/{sid}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == reply and msgs[1]["meta"]["ledger_seq"] == done["ledger_seq"]

    # Ledger holds hashes and counts, never the text itself.
    ev = eng.get("/ledger/events?event_type=llm.call").json()[0]
    assert ev["seq"] == done["ledger_seq"]
    assert ev["payload"]["response_sha256"] == hashlib.sha256(reply.encode()).hexdigest()
    assert "PSV" not in json.dumps(ev["payload"]) and reply not in json.dumps(ev["payload"])
    assert eng.get("/chat/sessions").json()[0]["title"] == "What is a PSV?"


def test_system_prompt_and_history_are_sent(app_env, client_for, mock_llm):
    eng = client_for("engineer")
    sid = eng.post("/chat/sessions", json={}).json()["id"]
    eng.post(f"/chat/sessions/{sid}/messages", json={"content": "first"})
    eng.post(f"/chat/sessions/{sid}/messages", json={"content": "second"})
    body = [b for kind, b in mock_llm.app.state.requests if kind == "chat"][-1]
    assert body["messages"][0]["role"] == "system" and "KILA" in body["messages"][0]["content"]
    assert [m["content"] for m in body["messages"][1:]] == ["first", "Answer from qwen3.5:4b.", "second"]
    assert body["reasoning_effort"] == "none" and body["stream_options"]["include_usage"] is True


def test_hot_swap_takes_effect_on_next_message(client_for):
    eng, admin = client_for("engineer"), client_for("admin")
    _, before = _chat(eng, "hi")
    admin.post("/models/small_text/activate", json={"name": "gemma4:e2b"})
    _, after = _chat(eng, "hi again")
    assert before[0][1]["model"] == "qwen3.5:4b"
    assert after[0][1]["model"] == "gemma4:e2b"
    assert "".join(d["text"] for k, d in after if k == "delta") == "Answer from gemma4:e2b."


def test_missing_model_streams_friendly_error(client_for):
    eng = client_for("engineer")
    _, evs = _chat(eng, "write code", role="coder")  # qwen2.5-coder not on the fake server
    assert evs[-1][0] == "error" and "isn't downloaded" in evs[-1][1]["detail"]
    ev = eng.get("/ledger/events?event_type=llm.call_failed").json()[0]["payload"]
    assert ev["model"] == "qwen2.5-coder:7b" and ev["status"] == "error"


def test_unreachable_backend(client_for, monkeypatch):
    from kila.models.registry import reset_registry

    monkeypatch.setenv("KILA_OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    reset_registry()
    _, evs = _chat(client_for("engineer"), "hello")
    assert evs[-1][0] == "error" and "Can't reach the model server" in evs[-1][1]["detail"]


def test_sessions_are_private(client_for):
    eng, rev = client_for("engineer"), client_for("reviewer")
    sid, _ = _chat(eng, "secret")
    assert rev.get(f"/chat/sessions/{sid}/messages").status_code == 404
    assert rev.post(f"/chat/sessions/{sid}/messages", json={"content": "x"}).status_code == 404
    assert client_for("admin").get(f"/chat/sessions/{sid}/messages").status_code == 200

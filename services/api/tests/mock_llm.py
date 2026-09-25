"""A tiny fake Ollama (native + OpenAI-compatible) server for offline tests.

Replies echo the model name so tests can prove which model actually answered.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

PULLED = {"qwen3.5:4b", "gemma4:e2b", "qwen3:8b"}


def make_app() -> FastAPI:
    app = FastAPI()
    state = {"loaded": set()}
    app.state.requests = []

    @app.get("/api/tags")
    def tags():
        return {"models": [{"name": n, "size": 1000} for n in sorted(PULLED)]}

    @app.get("/api/ps")
    def ps():
        return {"models": [{"name": n, "size": 1000, "size_vram": 900} for n in sorted(state["loaded"])]}

    @app.post("/api/generate")
    async def generate(req: Request):
        body = await req.json()
        app.state.requests.append(("generate", body))
        if body["model"] not in PULLED:
            return JSONResponse({"error": f"model '{body['model']}' not found"}, status_code=404)
        cold = body["model"] not in state["loaded"]
        state["loaded"] = {body["model"]}  # one resident model, like the laptop profile
        return {"response": "ok", "load_duration": 2_000_000_000 if cold else 1_000_000,
                "prompt_eval_count": 20, "prompt_eval_duration": 100_000_000,
                "eval_count": 50, "eval_duration": 1_000_000_000, "total_duration": 3_200_000_000}

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        app.state.requests.append(("chat", body))
        model = body["model"]
        if model not in PULLED:
            return JSONResponse({"error": {"message": f"model '{model}' not found"}}, status_code=404)
        state["loaded"] = {model}
        words = ["Answer", " from", f" {model}", "."]
        if any("[S1]" in str(m.get("content")) for m in body["messages"]):
            words = ["Answer", " from", f" {model}", " [S1]", "."]  # grounded prompt -> cite the first source

        def gen():
            base = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": model}
            for w in words:
                yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {"content": w},
                                                                  "finish_reason": None}]}) + "\n\n"
                time.sleep(0.01)
            yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            yield "data: " + json.dumps({**base, "choices": [], "usage": {
                "prompt_tokens": 30, "completion_tokens": len(words), "total_tokens": 30 + len(words)}}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


class MockLLMServer:
    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.app = make_app()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("mock LLM server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=5)

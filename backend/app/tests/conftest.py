"""Pytest fixtures: a real uvicorn server (TCP) so WebSocket + SSE are tested
end-to-end exactly as in production, plus a demo human worker connected over
the real WebSocket, and an httpx client pointed at the same server.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading

import httpx
import pytest
import pytest_asyncio
import uvicorn
import websockets

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# Use a file-based SQLite DB for tests so the uvicorn thread and the test
# thread do not share a single in-memory connection across event loops.
_TEST_DB = os.path.join(BACKEND, ".test_humanllm.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["AUTO_MIGRATE"] = "true"
os.environ["REDIS_URL"] = ""  # force in-memory broker

from app.main import app  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest_asyncio.fixture(scope="session")
async def app_server():
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    # Wait until the server is serving (lifespan runs migrations + seed).
    for _ in range(100):
        try:
            async with httpx.AsyncClient() as c:
                if (await c.get(base + "/health")).status_code == 200:
                    break
        except Exception:
            pass
        await asyncio.sleep(0.1)
    yield base
    server.should_exit = True
    t.join(timeout=5)
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


@pytest_asyncio.fixture
async def _migrated(app_server):
    yield app_server


@pytest_asyncio.fixture
async def client(app_server):
    async with httpx.AsyncClient(base_url=app_server, timeout=30) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(app_server):
    async with httpx.AsyncClient(base_url=app_server) as c:
        r = await c.post("/api/auth/worker/login", json={"username": "worker1", "password": "admin123"})
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def demo_worker(auth_headers, app_server):
    ws_url = app_server.replace("http", "ws") + f"/ws/worker?token={auth_headers['Authorization'].split(' ', 1)[1]}"
    ws = await websockets.connect(ws_url)
    running = True

    async def loop():
        while running:
            try:
                raw = await ws.recv()
            except Exception:
                break
            msg = json.loads(raw)
            if msg.get("type") == "task_assigned":
                task = msg["task"]
                content = task["messages"][-1].get("content")
                prompt = content if isinstance(content, str) else ""
                reply = "【人类真人回复】这是真人的验证回复。" + prompt
                for piece in [reply[i:i + 10] for i in range(0, len(reply), 10)]:
                    await ws.send(json.dumps({"type": "chunk", "task_id": task["id"], "text": piece}))
                    await asyncio.sleep(0.02)
                await ws.send(json.dumps({"type": "done", "task_id": task["id"], "text": reply}))

    task = asyncio.create_task(loop())
    await asyncio.sleep(0.4)
    yield
    running = False
    task.cancel()
    try:
        await ws.close()
    except Exception:
        pass

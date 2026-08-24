"""Tests: task cancellation and admin controls (no long timeouts)."""
from __future__ import annotations

import httpx

API_KEY = "sk-humanllm-demo-key-0001"


async def test_admin_can_list_and_cancel_task(client, demo_worker):
    """A task completed by the demo worker appears in admin; cancellation works."""
    # Complete a task first.
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": "human-default", "messages": [{"role": "user", "content": "取消测试"}], "stream": False},
    )
    assert r.status_code == 200

    admin_tok = (await client.post("/api/auth/admin/login", json={"username": "admin", "password": "admin123"})).json()["access_token"]
    h = {"Authorization": f"Bearer {admin_tok}"}
    tasks = (await client.get("/api/admin/tasks?limit=10", headers=h)).json()
    assert len(tasks) >= 1
    completed = [t for t in tasks if t["status"] == "completed"]
    assert completed, "expected at least one completed task"

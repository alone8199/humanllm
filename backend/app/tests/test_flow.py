"""Tests: worker auth, admin API, task lifecycle, grab-mode dispatch."""
from __future__ import annotations

API_KEY = "sk-humanllm-demo-key-0001"


async def test_worker_register_login(client):
    r = await client.post(
        "/api/auth/worker/register",
        json={"username": "tempworker", "password": "pw123", "skills": ["general"]},
    )
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    assert tok

    r2 = await client.post("/api/auth/worker/login", json={"username": "tempworker", "password": "pw123"})
    assert r2.status_code == 200


async def test_admin_login_and_stats(client):
    r = await client.post(
        "/api/auth/admin/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200, r.text
    admin_tok = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_tok}"}

    s = await client.get("/api/admin/stats", headers=h)
    assert s.status_code == 200
    assert "users" in s.json()

    models = await client.get("/api/admin/models", headers=h)
    assert models.status_code == 200
    assert len(models.json()) >= 5

    workers = await client.get("/api/admin/workers", headers=h)
    assert workers.status_code == 200
    assert any(w["username"] == "worker1" for w in workers.json())


async def test_admin_create_model_and_assign_worker(client):
    admin_tok = (await client.post("/api/auth/admin/login", json={"username": "admin", "password": "admin123"})).json()["access_token"]
    h = {"Authorization": f"Bearer {admin_tok}"}
    r = await client.post(
        "/api/admin/models",
        headers=h,
        json={"name": "human-test", "display_name": "Test", "worker_usernames": ["worker1"],
              "price_per_request_cents": 3},
    )
    assert r.status_code == 200, r.text
    assert r.json()["worker_usernames"] == ["worker1"]


async def test_grab_mode_dispatch(client, demo_worker):
    """With AUTO_ASSIGN on, a task is auto-assigned to the online worker."""
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": "human-default", "messages": [{"role": "user", "content": "抢单测试"}], "stream": False},
    )
    assert r.status_code == 200, r.text
    assert "真人" in r.json()["choices"][0]["message"]["content"]

"""Tests: file upload + multimodal message containing an image URL, and that
the worker receives the attachment; plus billing (balance debited, worker
earns, platform commission recorded).
"""
from __future__ import annotations

import json

API_KEY = "sk-humanllm-demo-key-0001"


async def test_file_upload_and_serve(client):
    files = {"file": ("hello.txt", b"hello humanllm", "text/plain")}
    r = await client.post("/v1/files", headers={"Authorization": f"Bearer {API_KEY}"}, files=files)
    assert r.status_code == 200, r.text
    obj = r.json()
    assert obj["filename"] == "hello.txt"
    assert obj["url"].endswith(obj["id"])

    # The file content endpoint requires auth.
    key = obj["id"]
    r2 = await client.get(f"/v1/files/content/{key}")
    assert r2.status_code == 401  # no auth
    r3 = await client.get(f"/v1/files/content/{key}", headers={"Authorization": f"Bearer {API_KEY}"})
    assert r3.status_code == 200
    assert r3.content == b"hello humanllm"


async def test_image_url_message_end_to_end(client, demo_worker):
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "human-default",
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "分析这张图片"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                    ],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert "真人" in r.json()["choices"][0]["message"]["content"]


async def test_billing(client, demo_worker, _migrated):
    # Capture balance before.
    async with __import__("app.database", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        from app.models import User

        user = (await db.execute(__import__("sqlalchemy").select(User).where(User.username == "demo"))).scalar_one()
        before = user.balance_cents

    # Run a (non-stream) completion.
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": "human-default", "messages": [{"role": "user", "content": "计费测试"}], "stream": False},
    )
    assert r.status_code == 200

    async with __import__("app.database", fromlist=["AsyncSessionLocal"]).AsyncSessionLocal() as db:
        from app.models import Transaction, User, Worker
        from sqlalchemy import select

        user = (await db.execute(select(User).where(User.username == "demo"))).scalar_one()
        after = user.balance_cents
        worker = (await db.execute(select(Worker).where(Worker.username == "worker1"))).scalar_one()
        txns = (await db.execute(select(Transaction).where(Transaction.kind.in_(["worker_earning", "platform_commission"])))).scalars().all()

    assert after < before, f"balance should decrease ({before} -> {after})"
    assert worker.earnings_cents > 0, "worker should earn something"
    assert any(t.kind.value == "worker_earning" for t in txns)
    assert any(t.kind.value == "platform_commission" for t in txns)

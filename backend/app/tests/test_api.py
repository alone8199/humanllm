"""Tests: OpenAI-compatible surface (models, auth, chat flow, files, billing)."""
from __future__ import annotations

import pytest

API_KEY = "sk-humanllm-demo-key-0001"


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_list_models(client):
    r = await client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()["data"]
    names = {m["id"] for m in data}
    assert {"human-default", "human-fast", "human-expert", "human-cn", "human-en"} <= names


async def test_auth_required(client):
    r = await client.post(
        "/v1/chat/completions",
        json={"model": "human-default", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "authentication_error"


async def test_auth_invalid_key(client):
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer sk-wrong"},
        json={"model": "human-default", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 401


async def test_unknown_model(client):
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": "does-not-exist", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 404


async def test_chat_nonstream_with_worker(client, demo_worker):
    r = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "human-default",
            "messages": [{"role": "user", "content": "你好，介绍一下自己。"}],
            "stream": False,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "真人" in body["choices"][0]["message"]["content"]
    assert body["usage"]["total_tokens"] >= 0


async def test_chat_stream_with_worker(client, demo_worker):
    collected = []
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": "human-default",
            "messages": [{"role": "user", "content": "流式测试"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    ) as resp:
        assert resp.status_code == 200
        full = ""
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            import json

            chunk = json.loads(payload)
            if chunk.get("choices") and chunk["choices"][0]["delta"].get("content"):
                full += chunk["choices"][0]["delta"]["content"]
        collected.append(full)
    assert "真人" in collected[0]

#!/usr/bin/env python3.11
"""Demo human worker.

Connects to the Worker Workbench WebSocket and, whenever a task is assigned,
replies like a human would: it acknowledges the prompt, references any images
/ files it was given, and streams the reply back in chunks. This proves the
full loop:

    OpenAI SDK -> /v1/chat/completions -> Task -> WS -> this script -> SSE -> SDK

Run (after the server is up):
    python3.11 scripts/demo_worker.py --base http://localhost:8000 \
        --username worker1 --password worker123
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import websockets  # provided by the `websockets` package

BASE = os.getenv("HUMANLLM_BASE", "http://localhost:8000")


def _human_reply(task: dict) -> str:
    """Compose a believable human reply from the task payload."""
    msgs = task.get("messages", [])
    last_user = ""
    n_images = 0
    n_files = 0
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            if m.get("role") == "user":
                last_user = c
        elif isinstance(c, list):
            for p in c:
                if isinstance(p, dict):
                    if p.get("type") == "text" and m.get("role") == "user":
                        last_user = p.get("text", "")
                    elif p.get("type") == "image_url":
                        n_images += 1
                    elif p.get("type") in ("file_url", "file"):
                        n_files += 1

    parts = [
        "【人类真人回复】我是真人 Worker，已收到你的请求。",
        f"你的问题是：{last_user[:200]}" if last_user else "你的问题是：（空）",
    ]
    if n_images:
        parts.append(f"我看到了你提供的 {n_images} 张图片，正在基于图片内容分析。")
    if n_files:
        parts.append(f"我还收到了 {n_files} 个文件附件，已查阅。")
    parts.append("这是一条由真人（而非 AI）给出的回复，用于验证 HumanLLM 的完整链路。")
    return "\n".join(parts)


async def run(base: str, username: str, password: str) -> None:
    # 1. Quick probe: ignore auth failure, just confirm ws endpoint is reachable.
    try:
        async with websockets.connect(base.replace("http", "ws") + "/ws/worker?token=dummy") as _:
            pass
    except Exception:
        pass

    import httpx

    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        resp = await client.post("/api/auth/worker/login", json={"username": username, "password": password})
        if resp.status_code != 200:
            raise SystemExit(f"Login failed: {resp.status_code} {resp.text}")
        token = resp.json()["access_token"]
        print(f"[demo-worker] logged in as {username}")

    ws_url = base.replace("http", "ws") + f"/ws/worker?token={token}"
    async with websockets.connect(ws_url) as ws:
        print("[demo-worker] connected to workbench WebSocket. Waiting for tasks...")
        async for raw in ws:
            msg = json.loads(raw)
            mtype = msg.get("type")
            if mtype == "task_assigned":
                task = msg["task"]
                print(f"[demo-worker] task {task['id']} assigned (model={task['model']})")
                reply = _human_reply(task)
                # Stream the reply back in chunks.
                chunks = [reply[i : i + 24] for i in range(0, len(reply), 24)]
                for ch in chunks:
                    await ws.send(json.dumps({"type": "chunk", "task_id": task["id"], "text": ch}))
                    await asyncio.sleep(0.15)
                await ws.send(json.dumps({"type": "done", "task_id": task["id"], "text": reply}))
                print(f"[demo-worker] task {task['id']} completed ({len(reply)} chars)")
            elif mtype == "new_task":
                print(f"[demo-worker] new task available: {msg['task_id']} (grab mode)")
            elif mtype == "error":
                print(f"[demo-worker] server error: {msg.get('message')}")
            elif mtype == "pong":
                pass


def main() -> None:
    ap = argparse.ArgumentParser(description="HumanLLM demo human worker")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--username", default=os.getenv("SEED_WORKER_USERNAME", "worker1"))
    ap.add_argument("--password", default=os.getenv("SEED_WORKER_PASSWORD", "worker123"))
    args = ap.parse_args()
    try:
        asyncio.run(run(args.base.rstrip("/"), args.username, args.password))
    except KeyboardInterrupt:
        print("\n[demo-worker] stopped.")


if __name__ == "__main__":
    main()

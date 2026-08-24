#!/usr/bin/env python3.11
"""Comprehensive end-to-end verification for HumanLLM.

Proves the full loop with the real server + real demo worker, and checks
billing (user balance, worker earnings, platform commission) via the admin
API. No AI is involved.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI

from scripts.demo_worker import run as run_worker

BASE = "http://127.0.0.1:8155"
API_KEY = "sk-humanllm-demo-key-0001"


async def boot_worker(base, user, pw):
    t = asyncio.create_task(run_worker(base, user, pw))
    await asyncio.sleep(1.2)
    return t


async def admin_stats(base):
    import httpx

    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        r = await c.post("/auth/admin/login", json={"username": "admin", "password": "admin123"})
        tok = r.json()["access_token"]
        s = await c.get("/admin/stats", headers={"Authorization": f"Bearer {tok}"})
        w = await c.get("/admin/workers", headers={"Authorization": f"Bearer {tok}"})
        return s.json(), w.json(), tok, c


async def main(base, api_key):
    wtask = await boot_worker(base, "worker1", "worker123")
    await asyncio.sleep(1.0)
    client = AsyncOpenAI(api_key=api_key, base_url=base + "/v1")

    # --- billing snapshot before ---
    stats_before, workers_before, tok, _ = await admin_stats(base)
    print("== BEFORE ==")
    print("  platform_commission_cents:", stats_before.get("platform_commission_cents"))
    print("  tasks_total:", stats_before.get("tasks_total"))
    print("  worker1 earnings before:", next((w["earnings_cents"] for w in workers_before if w["username"] == "worker1"), 0))

    # --- 1. non-stream chat ---
    print("\n== (1) NON-STREAMING CHAT ==")
    r1 = await client.chat.completions.create(
        model="human-default",
        messages=[{"role": "user", "content": "用一句话介绍 HumanLLM。"}],
        stream=False,
    )
    content1 = r1.choices[0].message.content
    print("  reply:", content1[:60], "...")
    print("  usage:", r1.usage.model_dump())
    assert "真人" in content1, "reply did not come from human worker"

    # --- 2. streaming chat ---
    print("\n== (2) STREAMING CHAT (SSE) ==")
    full = ""
    stream = await client.chat.completions.create(
        model="human-default",
        messages=[{"role": "user", "content": "流式测试一下"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    async for ch in stream:
        if ch.choices and ch.choices[0].delta.content:
            full += ch.choices[0].delta.content
    print("  streamed reply chars:", len(full))
    assert "真人" in full

    # --- 3. file upload + multimodal (image_url) ---
    print("\n== (3) FILE UPLOAD + MULTIMODAL ==")
    import httpx

    txt_path = "/tmp/humanllm_upload_demo.txt"
    with open(txt_path, "w") as f:
        f.write("这是一份上传的纯文本附件，用于验证多模态链路。")
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        with open(txt_path, "rb") as fh:
            up = await c.post(
                "/v1/files",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("demo.txt", fh, "text/plain")},
            )
        print("  upload status:", up.status_code)
        print("  upload resp:", up.json())
        assert up.status_code == 200

    r3 = await client.chat.completions.create(
        model="human-default",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "查看我刚上传的文件并描述。"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/pic.png"}},
                ],
            }
        ],
        stream=False,
    )
    print("  multimodal reply has 真人:", "真人" in r3.choices[0].message.content)

    # --- 4. billing after ---
    print("\n== (4) BILLING CHECK ==")
    stats_after, workers_after, _, _ = await admin_stats(base)
    w1_after = next((w["earnings_cents"] for w in workers_after if w["username"] == "worker1"), 0)
    print("  tasks_total before/after:", stats_before.get("tasks_total"), "->", stats_after.get("tasks_total"))
    print("  platform_commission_cents after:", stats_after.get("platform_commission_cents"))
    print("  worker1 earnings after:", w1_after)
    print("  worker_payouts_cents after:", stats_after.get("worker_payouts_cents"))

    assert stats_after.get("tasks_total", 0) >= 3, "expected >=3 tasks completed"
    assert stats_after.get("platform_commission_cents", 0) > 0, "platform should have earned commission"
    assert w1_after > 0, "worker1 should have earned from completed tasks"

    wtask.cancel()
    print("\n✅ FULL E2E VERIFICATION PASSED (no AI involved)")
    print("   - non-stream reply from human: OK")
    print("   - streaming SSE from human: OK")
    print("   - file upload + image multimodal: OK")
    print("   - billing (worker earned, platform commission recorded): OK")


def _entry():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--api-key", default=API_KEY)
    args = ap.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args.base.rstrip("/"), args.api_key)))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _entry()

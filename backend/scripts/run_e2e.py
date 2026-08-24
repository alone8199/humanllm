#!/usr/bin/env python3.11
"""End-to-end proof: OpenAI SDK -> HumanLLM API -> demo human worker -> response.

Start the server first (e.g. `uvicorn app.main:app --port 8000`), then run:

    python3.11 scripts/run_e2e.py

It boots a demo worker in-process, calls the API with the official OpenAI
Python SDK both in streaming and non-streaming mode, and prints the result.
No AI model is contacted at any point.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai import AsyncOpenAI  # noqa: E402

from app.broker import broker  # noqa: E402
from app.config import settings  # noqa: E402
from scripts.demo_worker import _human_reply, run as run_worker  # noqa: E402

BASE = "http://localhost:8000"
API_KEY = os.getenv("SEED_API_KEY", "sk-humanllm-demo-key-0001")


async def _boot_worker(base: str, username: str, password: str):
    # Run the demo worker's event loop as a background task until cancelled.
    import asyncio as _asyncio

    task = _asyncio.create_task(run_worker(base, username, password))
    # Give it a moment to connect.
    await _asyncio.sleep(1.0)
    return task


async def main(base: str, api_key: str) -> int:
    worker_task = await _boot_worker(base, settings.SEED_WORKER_USERNAME, settings.SEED_WORKER_PASSWORD)
    await asyncio.sleep(1.5)  # ensure WS connected & worker online

    client = AsyncOpenAI(api_key=api_key, base_url=base + "/v1")

    prompt = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "用一句话介绍 HumanLLM 项目。"},
    ]

    print("\n=== NON-STREAMING ===")
    resp = await client.chat.completions.create(model="human-default", messages=prompt, stream=False)
    print("model:", resp.model)
    print("reply:", resp.choices[0].message.content)
    print("usage:", resp.usage.model_dump())

    print("\n=== STREAMING (SSE) ===")
    collected = []
    stream = await client.chat.completions.create(model="human-default", messages=prompt, stream=True)
    async for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta and delta.content:
            collected.append(delta.content)
            print(delta.content, end="", flush=True)
    print("\n[stream done]")

    print("\n=== STREAMING WITH IMAGE ===")
    img_prompt = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "描述这张图片里有什么。"},
                {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            ],
        }
    ]
    collected2 = []
    stream2 = await client.chat.completions.create(model="human-default", messages=img_prompt, stream=True)
    async for chunk in stream2:
        if chunk.choices and chunk.choices[0].delta.content:
            collected2.append(chunk.choices[0].delta.content)
    print("image reply chars:", len("".join(collected2)))

    worker_task.cancel()
    print("\nE2E OK" if (resp.choices[0].message.content and "".join(collected)) else "E2E FAILED")
    return 0 if (resp.choices[0].message.content and "".join(collected)) else 1


def _entry() -> None:
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

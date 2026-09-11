"""Chat-domain helpers for the OpenAI-compatible endpoint.

The HTTP router should stay thin: request validation and transport belong in
routers/chat.py, while message normalization, off-hours responses, streaming,
and task timeout handling live here.
"""
from __future__ import annotations

import base64
import json
import random
import time
from datetime import datetime
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker import broker
from app.config import settings
from app.database import AsyncSessionLocal
from app.models import (
    ModelConfig,
    Task,
    TaskStatus,
    Transaction,
    TransactionKind,
    User,
    Worker,
    WorkerStatus,
)
from app.openai_errors import OpenAIError
from app.schemas import ChatCompletionRequest
from app.storage import storage


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def now() -> datetime:
    return datetime.utcnow()


async def store_data_url(data_url: str, kind: str) -> dict:
    header, _, b64 = data_url.partition(",")
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise OpenAIError("Invalid base64 data URL.", status_code=400, code="invalid_image")

    if len(raw) > settings.MAX_INLINE_BYTES:
        raise OpenAIError(
            f"Inline {kind} too large (max {settings.MAX_INLINE_BYTES} bytes).",
            status_code=413,
            code="payload_too_large",
        )

    mime = (
        header.split(":", 1)[1].split(";", 1)[0]
        if ":" in header
        else "application/octet-stream"
    )
    filename = f"inline.{mime.split('/')[-1]}"
    key = await storage.save(filename, mime, raw)
    return {
        "kind": kind,
        "source": "data",
        "url": storage.content_url(key),
        "filename": filename,
        "content_type": mime,
        "size": len(raw),
        "storage_key": key,
    }


async def normalize_message_content(content: Any) -> tuple[Any, list[dict]]:
    """Return normalized message content and extracted attachment metadata."""
    if content is None:
        return None, []
    if isinstance(content, str):
        return content, []

    parts: list[dict] = []
    metas: list[dict] = []
    if not isinstance(content, list):
        return json.dumps(content, ensure_ascii=False), metas

    for part in content:
        if not isinstance(part, dict):
            parts.append({"type": "text", "text": str(part)})
            continue

        ptype = part.get("type")
        if ptype == "text":
            parts.append({"type": "text", "text": part.get("text", "")})
        elif ptype == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:"):
                meta = await store_data_url(url, "image")
                metas.append(meta)
            else:
                metas.append(
                    {
                        "kind": "image",
                        "source": "url",
                        "url": url,
                        "filename": url.rsplit("/", 1)[-1].split("?", 1)[0] or "image",
                        "content_type": None,
                        "size": None,
                    }
                )
            parts.append({"type": "image_url", "image_url": {"url": metas[-1]["url"]}})
        elif ptype in ("file_url", "file"):
            url = (part.get("file_url") or part.get("file") or {}).get("url", "")
            if url.startswith("data:"):
                meta = await store_data_url(url, "file")
                metas.append(meta)
            else:
                metas.append(
                    {
                        "kind": "file",
                        "source": "url",
                        "url": url,
                        "filename": url.rsplit("/", 1)[-1].split("?", 1)[0] or "file",
                        "content_type": None,
                        "size": None,
                    }
                )
            parts.append({"type": "file_url", "file_url": {"url": metas[-1]["url"]}})
        else:
            parts.append({"type": "text", "text": json.dumps(part, ensure_ascii=False)})

    return parts, metas


async def normalize_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    norm: list[dict] = []
    all_metas: list[dict] = []
    for message in messages:
        norm_content, metas = await normalize_message_content(message.get("content"))
        all_metas.extend(metas)
        msg: dict = {
            "role": message.get("role", "user"),
            "content": norm_content,
            "name": message.get("name"),
        }
        if message.get("role") == "tool":
            msg["tool_call_id"] = message.get("tool_call_id")
        if message.get("tool_calls"):
            msg["tool_calls"] = message.get("tool_calls")
        norm.append(msg)
    return norm, all_metas


async def find_continuation(
    db: AsyncSession, api_key_id: int, model: str, messages: list[dict]
) -> Task | None:
    """Find a waiting_tool task that matches a tool-call continuation."""
    tool_ids = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    if not tool_ids:
        return None

    result = await db.execute(
        select(Task)
        .where(
            Task.api_key_id == api_key_id,
            Task.model == model,
            Task.status == TaskStatus.waiting_tool,
        )
        .order_by(Task.created_at.desc())
        .limit(20)
    )
    for task in result.scalars().all():
        calls = task.tool_calls or []
        known = {call.get("id") for call in calls if isinstance(call, dict)}
        if any(tool_id in known for tool_id in tool_ids):
            return task
    return None


def off_hours_active() -> bool:
    if not settings.OFF_HOURS_ENABLED:
        return False
    hour = datetime.now().hour
    start, end = settings.OFF_HOURS_START, settings.OFF_HOURS_END
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


_OFF_HOURS_REPLIES = [
    "喵~现在是深夜时段（20:00-08:00），本模型已经睡觉觉啦！明天白天再来找我玩哦～(=^･ω･^=)",
    "唔…现在是休息时间呢，人类也要好好睡觉的呀！晚上 8 点到早上 8 点，本模型处于离线模式，明天见啦～(≧▽≦)",
    "呀！都这么晚啦，主人怎么还不睡？模型酱已经下班了喵～白天 8 点以后再来找我说话吧！(๑•̀ㅂ•́)و✧",
    "呼噜…呼噜…(｡˘•ε•˘｡) 现在是凌晨/夜晚时段，本模型正在梦里吃团子。营业时间：早上 8 点～晚上 8 点，到时候见！",
]


def off_hours_response(req: ChatCompletionRequest):
    """Build an OpenAI-compatible response without creating a task."""
    reply = random.choice(_OFF_HOURS_REPLIES)
    created = int(time.time())
    model = req.model
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": len(reply),
        "total_tokens": len(reply),
    }

    if req.stream:
        async def generate():
            yield sse(
                {
                    "id": "chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
            )
            yield sse(
                {
                    "id": "chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": reply}, "finish_reason": None}],
                }
            )
            yield sse(
                {
                    "id": "chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": usage if (req.stream_options and req.stream_options.include_usage) else None,
                }
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return {
        "id": "chatcmpl-off",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


async def stream_task(task: Task, model_cfg: ModelConfig, include_usage: bool):
    task_id = task.id
    model = task.model
    created = int(time.time())
    sent_content = False

    try:
        yield sse(
            {
                "id": f"chatcmpl-{task_id}",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
        )

        timeout = max(1.0, (task.timeout_at - now()).total_seconds())
        async for event in broker.consume(task_id, timeout):
            event_type = event.get("type")
            if event_type == "chunk":
                sent_content = True
                yield sse(
                    {
                        "id": f"chatcmpl-{task_id}",
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": {"content": event.get("text", "")}, "finish_reason": None}
                        ],
                    }
                )
            elif event_type == "done":
                usage = event.get("usage")
                finish_reason = event.get("finish_reason", "stop")
                tool_calls = event.get("tool_calls")
                delta: dict = {}
                if tool_calls:
                    delta["tool_calls"] = tool_calls
                done_text = event.get("text")
                if done_text and not tool_calls and not sent_content:
                    delta["content"] = done_text
                yield sse(
                    {
                        "id": f"chatcmpl-{task_id}",
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                        "usage": usage if include_usage else None,
                    }
                )
                yield "data: [DONE]\n\n"
                return
            elif event_type == "timeout":
                await timeout_task(task_id)
                yield sse({"error": {"message": "The request timed out: no human worker completed it in time.", "type": "timeout", "code": "timeout"}})
                return
            elif event_type == "cancelled":
                yield sse({"error": {"message": "The task was cancelled.", "type": "cancelled", "code": "cancelled"}})
                return
            elif event_type == "error":
                yield sse({"error": {"message": event.get("message", "Worker error."), "type": "worker_error", "code": "worker_error"}})
                return
    finally:
        broker.unregister_task(task_id)


async def collect_task(task: Task, model_cfg: ModelConfig, include_usage: bool):
    task_id = task.id
    model = task.model
    created = int(time.time())
    timeout = max(1.0, (task.timeout_at - now()).total_seconds())
    reply = ""
    usage = None
    terminal_error = None

    async for event in broker.consume(task_id, timeout):
        event_type = event.get("type")
        if event_type == "chunk":
            reply += event.get("text", "")
        elif event_type == "done":
            usage = event.get("usage")
            finish_reason = event.get("finish_reason", "stop")
            tool_calls = event.get("tool_calls")
            done_text = event.get("text")
            if done_text:
                reply = done_text
            elif tool_calls and not reply:
                reply = ""
            break
        elif event_type == "timeout":
            await timeout_task(task_id)
            raise OpenAIError(
                "The request timed out: no human worker completed it in time.",
                status_code=504,
                error_type="timeout",
                code="timeout",
            )
        elif event_type == "cancelled":
            raise OpenAIError("The task was cancelled.", status_code=409, code="cancelled")
        elif event_type == "error":
            raise OpenAIError(event.get("message", "Worker error."), status_code=500, code="worker_error")

    broker.unregister_task(task_id)

    if usage is None:
        raise OpenAIError("Task ended without a reply.", status_code=500, code="no_reply")

    message: dict = {"role": "assistant", "content": reply}
    if tool_calls:
        message["tool_calls"] = tool_calls
        if not reply:
            message["content"] = None

    return {
        "id": f"chatcmpl-{task_id}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
        },
    }


async def timeout_task(task_id: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.status in (
            TaskStatus.completed,
            TaskStatus.failed,
            TaskStatus.cancelled,
            TaskStatus.timeout,
        ):
            return

        task.status = TaskStatus.timeout
        task.error = "timed out"
        user = await db.get(User, task.user_id) if task.user_id else None
        if user is not None and task.precharge_cents:
            user.balance_cents += task.precharge_cents
            db.add(
                Transaction(
                    task_id=task.id,
                    kind=TransactionKind.refund,
                    user_id=user.id,
                    amount_cents=task.precharge_cents,
                    note="refund on timeout",
                )
            )

        if task.assigned_worker_id:
            worker = await db.get(Worker, task.assigned_worker_id)
            if worker:
                worker.status = WorkerStatus.online if worker.current_task_id == task_id else worker.status
                worker.current_task_id = None

        await db.commit()

"""Core OpenAI-compatible chat completions endpoint.

Human-in-the-loop: a request creates a Task, the task is dispatched to a
human worker (auto-assign or grab), and the worker's reply is streamed back
to the caller as Server-Sent Events (or collected for a normal JSON response).
No AI model is ever contacted.
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import hold_precharge, precharge_cents, settle, sum_prompt_chars
from app.broker import broker
from app.config import settings
from app.database import AsyncSessionLocal, get_session
from app.dispatch import auto_assign, enqueue_for_grab
from app.deps import authenticate_api_key
from app.models import (
    Attachment,
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
from app.ratelimit import limiter
from app.schemas import ChatCompletionRequest
from app.storage import storage
from app.tools import merge_builtin_tools

router = APIRouter()


# ------------------------------ helpers ------------------------------
def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _now() -> datetime:
    return datetime.utcnow()


async def _store_data_url(data_url: str, kind: str) -> dict:
    header, _, b64 = data_url.partition(",")
    try:
        raw = base64.b64decode(b64)
    except Exception:
        raise OpenAIError("Invalid base64 data URL.", status_code=400, code="invalid_image")
    # Reject oversized inline attachments (memory/disk DoS guard).
    if len(raw) > settings.MAX_INLINE_BYTES:
        raise OpenAIError(
            f"Inline {kind} too large (max {settings.MAX_INLINE_BYTES} bytes).",
            status_code=413,
            code="payload_too_large",
        )
    mime = header.split(":", 1)[1].split(";", 1)[0] if ":" in header else "application/octet-stream"
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


async def _normalize_message_content(content: Any) -> tuple[Any, list[dict]]:
    """Return (normalized_content, attachment_metas)."""
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
                meta = await _store_data_url(url, "image")
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
                meta = await _store_data_url(url, "file")
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


async def _normalize_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    norm: list[dict] = []
    all_metas: list[dict] = []
    for m in messages:
        content = m.get("content")
        norm_content, metas = await _normalize_message_content(content)
        all_metas.extend(metas)
        msg: dict = {
            "role": m.get("role", "user"),
            "content": norm_content,
            "name": m.get("name"),
        }
        # Preserve tool-call linkage so follow-up requests can be matched to
        # the original waiting_tool task (same-session continuation).
        if m.get("role") == "tool":
            msg["tool_call_id"] = m.get("tool_call_id")
        if m.get("tool_calls"):
            msg["tool_calls"] = m.get("tool_calls")
        norm.append(msg)
    return norm, all_metas


# ------------------------------ endpoint ------------------------------
async def _find_continuation(
    db: AsyncSession, api_key_id: int, model: str, messages: list[dict]
) -> Task | None:
    """If this request carries tool-role results, find the waiting_tool task
    (same api key + model + tool_call_id) so the conversation continues on the
    same task instead of spawning a new one."""
    tool_ids = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    if not tool_ids:
        return None
    res = await db.execute(
        select(Task)
        .where(
            Task.api_key_id == api_key_id,
            Task.model == model,
            Task.status == TaskStatus.waiting_tool,
        )
        .order_by(Task.created_at.desc())
        .limit(20)
    )
    for t in res.scalars().all():
        calls = t.tool_calls or []
        known = {c.get("id") for c in calls if isinstance(c, dict)}
        if any(tid in known for tid in tool_ids):
            return t
    return None


def _off_hours_active() -> bool:
    """True when the server's local time is outside business hours
    (after OFF_HOURS_START or before OFF_HOURS_END)."""
    if not settings.OFF_HOURS_ENABLED:
        return False
    h = datetime.now().hour
    start, end = settings.OFF_HOURS_START, settings.OFF_HOURS_END
    if start > end:
        # Overnight window, e.g. 20 -> 08: active if h >= 20 or h < 8.
        return h >= start or h < end
    return h >= start and h < end


# 二次元休息文案：夜晚/凌晨时段自动回复（HTTP 200，但内容是"人已下线"）。
_OFF_HOURS_REPLIES = [
    "喵~现在是深夜时段（20:00-08:00），本模型已经睡觉觉啦！明天白天再来找我玩哦～(=^･ω･^=)",
    "唔…现在是休息时间呢，人类也要好好睡觉的呀！晚上 8 点到早上 8 点，本模型处于离线模式，明天见啦～(≧▽≦)",
    "呀！都这么晚啦，主人怎么还不睡？模型酱已经下班了喵～白天 8 点以后再来找我说话吧！(๑•̀ㅂ•́)و✧",
    "呼噜…呼噜…(｡˘•ε•˘｡) 现在是凌晨/夜晚时段，本模型正在梦里吃团子。营业时间：早上 8 点～晚上 8 点，到时候见！",
]


def _off_hours_reply() -> str:
    import random

    return random.choice(_OFF_HOURS_REPLIES)


def _off_hours_response(req, api_key):
    """Build a standard OpenAI chat.completion response that says the human
    model is off-duty — HTTP 200, no task created, no worker woken up."""
    reply = _off_hours_reply()
    created = int(time.time())
    model = req.model
    usage = {
        "prompt_tokens": 0,
        "completion_tokens": len(reply),
        "total_tokens": len(reply),
    }
    if req.stream:
        async def gen():
            yield _sse(
                {
                    "id": f"chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
                }
            )
            # Emit the whole reply in one chunk.
            yield _sse(
                {
                    "id": f"chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": reply}, "finish_reason": None}],
                }
            )
            yield _sse(
                {
                    "id": f"chatcmpl-off",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": usage if (req.stream_options and req.stream_options.include_usage) else None,
                }
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    return {
        "id": f"chatcmpl-off",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
        "usage": usage,
    }


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    api_key=Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_session),
):
    # Per-API-key rate limit (anti-abuse / cost runaway guard).
    if settings.RATE_LIMIT_ENABLED:
        allowed, _rem, retry_after = limiter.check(
            f"chat:key:{api_key.id}", settings.RATE_APIKEY_CHAT_PER_MIN, 60
        )
        if not allowed:
            raise OpenAIError(
                "Rate limit exceeded for this API key. Slow down and retry later.",
                status_code=429,
                error_type="rate_limit_error",
                code="rate_limited",
            )

    # 0. Off-hours: don't refuse, but auto-reply with a 二次元 "resting" message
    # (HTTP 200, standard chat.completion shape). No task is created and no
    # human worker is bothered.
    if settings.OFF_HOURS_ENABLED and _off_hours_active():
        return _off_hours_response(req, api_key)

    # 1. Resolve & validate model.
    model_cfg = (
        await db.execute(
            select(ModelConfig).where(
                ModelConfig.name == req.model, ModelConfig.is_active == True  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if model_cfg is None:
        raise OpenAIError(
            f"The model '{req.model}' does not exist or is not available.",
            status_code=404,
            error_type="invalid_request_error",
            code="model_not_found",
        )

    user = await db.get(User, api_key.user_id)
    if user is None:
        raise OpenAIError("Owner account not found.", status_code=403, code="account_error")

    # 2. Normalize messages + extract attachments.
    messages_norm, attachment_metas = await _normalize_messages(
        [m.model_dump() for m in req.messages]
    )

    # 3. Same-session continuation: a follow-up request carrying tool results
    # resumes the original waiting_tool task (same conversation, same worker).
    continuation = await _find_continuation(db, api_key.id, req.model, messages_norm)

    if continuation is not None:
        task = continuation
        task.messages = messages_norm
        task.stream = req.stream
        task.status = TaskStatus.pending
        task.assigned_worker_id = None
        task.assigned_at = None
        task.reply_text = ""
        task.tool_calls = None
        task.finish_reason = None
        task.timeout_at = _now() + __import__("datetime").timedelta(seconds=model_cfg.timeout_seconds)
        await db.commit()
        prompt_chars = sum_prompt_chars(messages_norm)
        task.precharge_cents = precharge_cents(model_cfg, prompt_chars)
    else:
        # Fresh conversation: create the task (pending until dispatched).
        # Built-in tools (run_shell, ...) are always available to the human
        # worker regardless of what the caller declared.
        task = Task(
            model=req.model,
            user_id=user.id,
            api_key_id=api_key.id,
            messages=messages_norm,
            status=TaskStatus.pending,
            stream=req.stream,
            tools=merge_builtin_tools(req.tools),
            session_id=str(uuid.uuid4()),
        )
        prompt_chars = sum_prompt_chars(messages_norm)
        task.precharge_cents = precharge_cents(model_cfg, prompt_chars)
        task.timeout_at = _now() + __import__("datetime").timedelta(seconds=model_cfg.timeout_seconds)
        db.add(task)
        await db.flush()

        for meta in attachment_metas:
            db.add(
                Attachment(
                    task_id=task.id,
                    kind=meta["kind"],
                    source=meta["source"],
                    filename=meta.get("filename", ""),
                    content_type=meta.get("content_type"),
                    storage_key=meta.get("storage_key"),
                    url=meta.get("url"),
                    size=meta.get("size"),
                )
            )
        await db.commit()
        await hold_precharge(db, task, user, model_cfg, task.precharge_cents)

    # 4. Register the live channel, then dispatch.
    broker.register_task(task.id)
    assigned = False
    if settings.AUTO_ASSIGN:
        assigned = await auto_assign(db, task, model_cfg)
    if not assigned:
        await enqueue_for_grab(db, task)

    include_usage = bool(req.stream_options and req.stream_options.include_usage)

    if req.stream:
        return StreamingResponse(
            _stream(task, model_cfg, include_usage),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    return await _collect(task, model_cfg, include_usage)


# --------------------------- streaming path ---------------------------
async def _stream(task: Task, model_cfg: ModelConfig, include_usage: bool):
    task_id = task.id
    model = task.model
    created = int(time.time())
    sent_content = False  # whether any content chunk has been emitted so far
    try:
        yield _sse(
            {
                "id": f"chatcmpl-{task_id}",
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
        )
        timeout = max(1.0, (task.timeout_at - _now()).total_seconds())
        async for ev in broker.consume(task_id, timeout):
            etype = ev.get("type")
            if etype == "chunk":
                sent_content = True
                yield _sse(
                    {
                        "id": f"chatcmpl-{task_id}",
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": {"content": ev.get("text", "")}, "finish_reason": None}
                        ],
                    }
                )
            elif etype == "done":
                usage = ev.get("usage")
                finish_reason = ev.get("finish_reason", "stop")
                tool_calls = ev.get("tool_calls")
                delta: dict = {}
                if tool_calls:
                    delta["tool_calls"] = tool_calls
                # Only deliver the full text in the final delta if the worker
                # finalized WITHOUT streaming chunks first (e.g. typed the whole
                # reply and hit Finish). If chunks were already streamed, adding
                # the full text again would duplicate the reply.
                done_text = ev.get("text")
                if done_text and not tool_calls and not sent_content:
                    delta["content"] = done_text
                yield _sse(
                    {
                        "id": f"chatcmpl-{task_id}",
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish_reason}
                        ],
                        "usage": usage if include_usage else None,
                    }
                )
                yield "data: [DONE]\n\n"
                return
            elif etype == "timeout":
                await _timeout_task(task_id)
                yield _sse(
                    {
                        "error": {
                            "message": "The request timed out: no human worker completed it in time.",
                            "type": "timeout",
                            "code": "timeout",
                        }
                    }
                )
                return
            elif etype == "cancelled":
                yield _sse(
                    {
                        "error": {
                            "message": "The task was cancelled.",
                            "type": "cancelled",
                            "code": "cancelled",
                        }
                    }
                )
                return
            elif etype == "error":
                yield _sse(
                    {
                        "error": {
                            "message": ev.get("message", "Worker error."),
                            "type": "worker_error",
                            "code": "worker_error",
                        }
                    }
                )
                return
    finally:
        broker.unregister_task(task_id)


# -------------------------- non-stream path ---------------------------
async def _collect(task: Task, model_cfg: ModelConfig, include_usage: bool):
    task_id = task.id
    model = task.model
    created = int(time.time())
    timeout = max(1.0, (task.timeout_at - _now()).total_seconds())
    reply = ""
    usage = None
    terminal_error = None
    async for ev in broker.consume(task_id, timeout):
        etype = ev.get("type")
        if etype == "chunk":
            reply += ev.get("text", "")
        elif etype == "done":
            usage = ev.get("usage")
            finish_reason = ev.get("finish_reason", "stop")
            tool_calls = ev.get("tool_calls")
            # The worker may finalize with the full text in the done event
            # (e.g. they typed the reply and hit Finish without sending
            # chunks first). Prefer the done text over chunk accumulation
            # so the caller always receives the complete reply.
            done_text = ev.get("text")
            if done_text:
                reply = done_text
            elif tool_calls and not reply:
                reply = ""
            break
        elif etype == "timeout":
            await _timeout_task(task_id)
            raise OpenAIError(
                "The request timed out: no human worker completed it in time.",
                status_code=504,
                error_type="timeout",
                code="timeout",
            )
        elif etype == "cancelled":
            raise OpenAIError("The task was cancelled.", status_code=409, code="cancelled")
        elif etype == "error":
            raise OpenAIError(ev.get("message", "Worker error."), status_code=500, code="worker_error")
    broker.unregister_task(task_id)

    if usage is None:
        # Safety net (should not happen if 'done' was emitted).
        raise OpenAIError("Task ended without a reply.", status_code=500, code="no_reply")

    message: dict = {"role": "assistant", "content": reply}
    if tool_calls:
        # Human-in-the-loop function calling: surface the worker-filled calls.
        message["tool_calls"] = tool_calls
        if not reply:
            message["content"] = None
    return {
        "id": f"chatcmpl-{task_id}",
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {"index": 0, "message": message, "finish_reason": finish_reason}
        ],
        "usage": {
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
        },
    }


# ---------------------------- timeout ----------------------------
async def _timeout_task(task_id: str) -> None:
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

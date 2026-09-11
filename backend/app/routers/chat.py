"""OpenAI-compatible chat completions HTTP endpoint.

The router is intentionally thin. Chat-domain behavior lives in
``app.services.chat`` so transport concerns stay separate from task handling.
No AI model is ever contacted.
"""
from __future__ import annotations

import time
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import hold_precharge, precharge_cents, sum_prompt_chars
from app.broker import broker
from app.config import settings
from app.database import get_session
from app.dispatch import auto_assign, enqueue_for_grab
from app.deps import authenticate_api_key
from app.models import Attachment, ModelConfig, Task, TaskStatus, User
from app.openai_errors import OpenAIError
from app.ratelimit import limiter
from app.schemas import ChatCompletionRequest
from app.services.chat import (
    collect_task,
    find_continuation,
    normalize_messages,
    now,
    off_hours_active,
    off_hours_response,
    stream_task,
)
from app.tools import merge_builtin_tools

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    api_key=Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_session),
):
    """Create or continue a human-response task and expose its result."""
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

    # Off-hours responses never create a task or wake a human worker.
    if settings.OFF_HOURS_ENABLED and off_hours_active():
        return off_hours_response(req)

    model_cfg = (
        await db.execute(
            select(ModelConfig).where(
                ModelConfig.name == req.model,
                ModelConfig.is_active == True,  # noqa: E712
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

    messages_norm, attachment_metas = await normalize_messages(
        [message.model_dump() for message in req.messages]
    )
    continuation = await find_continuation(
        db, api_key.id, req.model, messages_norm
    )

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
        task.timeout_at = now() + timedelta(seconds=model_cfg.timeout_seconds)
        prompt_chars = sum_prompt_chars(messages_norm)
        task.precharge_cents = precharge_cents(model_cfg, prompt_chars)
        await db.commit()
    else:
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
        task.timeout_at = now() + timedelta(seconds=model_cfg.timeout_seconds)
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

    broker.register_task(task.id)
    assigned = False
    if settings.AUTO_ASSIGN:
        assigned = await auto_assign(db, task, model_cfg)
    if not assigned:
        await enqueue_for_grab(db, task)

    include_usage = bool(
        req.stream_options and req.stream_options.include_usage
    )
    if req.stream:
        return StreamingResponse(
            stream_task(task, model_cfg, include_usage),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return await collect_task(task, model_cfg, include_usage)

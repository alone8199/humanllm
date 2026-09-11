"""Application service for creating, continuing, and dispatching chat tasks."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import hold_precharge, precharge_cents, sum_prompt_chars
from app.broker import broker
from app.config import settings
from app.dispatch import auto_assign, enqueue_for_grab
from app.models import Attachment, ModelConfig, Task, TaskStatus, User
from app.schemas import ChatCompletionRequest
from app.services.chat import find_continuation, normalize_messages, now
from app.tools import merge_builtin_tools


async def create_or_continue_task(
    db: AsyncSession,
    req: ChatCompletionRequest,
    api_key,
    user: User,
    model_cfg: ModelConfig,
) -> Task:
    """Create a fresh task or resume a waiting tool-call task."""
    messages, attachment_metas = await normalize_messages(
        [message.model_dump() for message in req.messages]
    )
    continuation = await find_continuation(db, api_key.id, req.model, messages)

    if continuation is not None:
        task = continuation
        task.messages = messages
        task.stream = req.stream
        task.status = TaskStatus.pending
        task.assigned_worker_id = None
        task.assigned_at = None
        task.reply_text = ""
        task.tool_calls = None
        task.finish_reason = None
        task.timeout_at = now() + timedelta(seconds=model_cfg.timeout_seconds)
        task.precharge_cents = precharge_cents(
            model_cfg, sum_prompt_chars(messages)
        )
        await db.commit()
        return task

    task = Task(
        model=req.model,
        user_id=user.id,
        api_key_id=api_key.id,
        messages=messages,
        status=TaskStatus.pending,
        stream=req.stream,
        tools=merge_builtin_tools(req.tools),
        session_id=str(uuid.uuid4()),
    )
    task.precharge_cents = precharge_cents(
        model_cfg, sum_prompt_chars(messages)
    )
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
    return task


async def dispatch_task(db: AsyncSession, task: Task, model_cfg: ModelConfig) -> None:
    """Register a live task and dispatch it to an available human worker."""
    broker.register_task(task.id)
    assigned = False
    if settings.AUTO_ASSIGN:
        assigned = await auto_assign(db, task, model_cfg)
    if not assigned:
        await enqueue_for_grab(db, task)

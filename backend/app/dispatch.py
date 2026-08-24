"""Dispatch logic shared by the chat endpoint (auto-assign) and the worker
WebSocket (grab / disconnect reassign). No AI is involved: a human worker is
chosen from the model's online worker pool.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker import broker
from app.config import settings
from app.models import (
    Attachment,
    ModelConfig,
    Task,
    TaskStatus,
    Worker,
    WorkerModel,
    WorkerStatus,
)


async def candidate_worker_ids(db: AsyncSession, model_name: str) -> list[int]:
    """Online workers that are members of the model's pool."""
    result = await db.execute(
        select(Worker.id)
        .join(WorkerModel, WorkerModel.worker_id == Worker.id)
        .where(
            WorkerModel.model_name == model_name,
            Worker.status == WorkerStatus.online,
            Worker.is_active == True,  # noqa: E712
        )
    )
    return [r[0] for r in result.all()]


async def active_task_count(db: AsyncSession, worker_id: int) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Task)
        .where(
            Task.assigned_worker_id == worker_id,
            Task.status.in_([TaskStatus.assigned, TaskStatus.streaming]),
        )
    )
    return int(result.scalar() or 0)


async def assign_to_worker(
    db: AsyncSession, task: Task, worker: Worker, model_cfg: ModelConfig
) -> None:
    task.assigned_worker_id = worker.id
    task.status = TaskStatus.assigned
    task.assigned_at = datetime.utcnow()
    worker.status = WorkerStatus.busy
    worker.current_task_id = task.id
    await broker.remove_pending(task.model, task.id)
    await db.commit()
    await _send_assigned(db, task, worker)


async def _send_assigned(db: AsyncSession, task: Task, worker: Worker) -> None:
    result = await db.execute(select(Attachment).where(Attachment.task_id == task.id))
    attachments = [
        {
            "id": a.id,
            "kind": a.kind,
            "url": a.url,
            "filename": a.filename,
            "content_type": a.content_type,
        }
        for a in result.scalars().all()
    ]
    broker.send_to_worker(
        worker.id,
        {
            "type": "task_assigned",
            "task": {
                "id": task.id,
                "model": task.model,
                "messages": task.messages,
                "tools": task.tools,
                "stream": task.stream,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "attachments": attachments,
            },
        },
    )


async def auto_assign(db: AsyncSession, task: Task, model_cfg: ModelConfig) -> bool:
    """Pick the least-busy eligible worker and assign. Returns True if assigned."""
    candidates = await candidate_worker_ids(db, task.model)
    if not candidates:
        return False
    ranked = []
    for wid in candidates:
        if task.assigned_worker_id == wid:
            continue
        count = await active_task_count(db, wid)
        if count >= model_cfg.concurrency:
            continue
        ranked.append((count, wid))
    if not ranked:
        return False
    ranked.sort(key=lambda x: x[0])
    worker = await db.get(Worker, ranked[0][1])
    await assign_to_worker(db, task, worker, model_cfg)
    return True


async def enqueue_for_grab(db: AsyncSession, task: Task) -> None:
    await broker.enqueue_pending(task.model, task.id)
    candidates = await candidate_worker_ids(db, task.model)
    await broker.notify_new_task(task.model, task.id, candidates)


async def requeue_task(db: AsyncSession, task: Task) -> None:
    """Return a task to the pending pool (after worker disconnect / reassign)."""
    task.assigned_worker_id = None
    task.status = TaskStatus.pending
    task.assigned_at = None
    await db.commit()
    await enqueue_for_grab(db, task)
    if settings.AUTO_ASSIGN:
        model_cfg = (await db.execute(
            select(ModelConfig).where(ModelConfig.name == task.model)
        )).scalar_one_or_none()
        if model_cfg:
            await auto_assign(db, task, model_cfg)


def task_payload_for_public(task: Task) -> dict:
    return {
        "id": task.id,
        "model": task.model,
        "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        "stream": task.stream,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }

"""Task dispatch service for HumanLLM.

Keeps worker selection, assignment, queueing, and reassignment out of the
HTTP/WebSocket routers while preserving the existing app.dispatch API through
the compatibility module.
"""
from __future__ import annotations

from datetime import datetime

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
    """Return active online workers that belong to the model's worker pool."""
    result = await db.execute(
        select(Worker.id)
        .join(WorkerModel, WorkerModel.worker_id == Worker.id)
        .where(
            WorkerModel.model_name == model_name,
            Worker.status == WorkerStatus.online,
            Worker.is_active.is_(True),
        )
    )
    return [row[0] for row in result.all()]


async def active_task_count(db: AsyncSession, worker_id: int) -> int:
    """Count assigned or streaming tasks currently held by a worker."""
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
    """Assign a task, update worker state, and notify the worker."""
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
            "id": attachment.id,
            "kind": attachment.kind,
            "url": attachment.url,
            "filename": attachment.filename,
            "content_type": attachment.content_type,
        }
        for attachment in result.scalars().all()
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
    """Assign the least-busy eligible worker, respecting model concurrency."""
    candidates = await candidate_worker_ids(db, task.model)
    if not candidates:
        return False

    ranked: list[tuple[int, int]] = []
    for worker_id in candidates:
        if task.assigned_worker_id == worker_id:
            continue
        count = await active_task_count(db, worker_id)
        if count >= model_cfg.concurrency:
            continue
        ranked.append((count, worker_id))

    if not ranked:
        return False

    ranked.sort(key=lambda item: item[0])
    worker = await db.get(Worker, ranked[0][1])
    if worker is None:
        return False
    await assign_to_worker(db, task, worker, model_cfg)
    return True


async def enqueue_for_grab(db: AsyncSession, task: Task) -> None:
    """Put a task into the pending pool and notify eligible workers."""
    await broker.enqueue_pending(task.model, task.id)
    candidates = await candidate_worker_ids(db, task.model)
    await broker.notify_new_task(task.model, task.id, candidates)


async def requeue_task(db: AsyncSession, task: Task) -> None:
    """Return a task to the pending pool after worker disconnect/reassignment."""
    task.assigned_worker_id = None
    task.status = TaskStatus.pending
    task.assigned_at = None
    await db.commit()
    await enqueue_for_grab(db, task)

    if settings.AUTO_ASSIGN:
        result = await db.execute(
            select(ModelConfig).where(ModelConfig.name == task.model)
        )
        model_cfg = result.scalar_one_or_none()
        if model_cfg:
            await auto_assign(db, task, model_cfg)


def task_payload_for_public(task: Task) -> dict:
    """Return the stable public representation used by API responses."""
    return {
        "id": task.id,
        "model": task.model,
        "status": task.status.value if isinstance(task.status, TaskStatus) else task.status,
        "stream": task.stream,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }

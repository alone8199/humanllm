"""Worker-facing API: WebSocket workbench channel + REST helpers.

Over the WebSocket a human worker receives assigned tasks, streams reply
chunks in real time, and finalizes. The server relays those chunks to the
waiting /v1/chat/completions caller (SSE or buffered JSON).
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, WebSocket, WebSocketDisconnect
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import settle, sum_prompt_chars
from app.broker import broker
from app.config import settings
from app.database import AsyncSessionLocal, get_session
from app.deps import get_worker_from_token
from app.dispatch import assign_to_worker, candidate_worker_ids
from app.models import (
    Attachment,
    ModelConfig,
    Task,
    TaskStatus,
    Transaction,
    TransactionKind,
    User,
    Worker,
    WorkerModel,
    WorkerStatus,
)
from app.schemas import WorkerPublic
from app.security import decode_access_token

router = APIRouter()
ws_router = APIRouter()  # mounted without /api prefix so /ws/worker stays as-is


# ------------------------------ REST ------------------------------
@router.get("/worker/me", response_model=WorkerPublic)
async def worker_me(worker: Worker = Depends(get_worker_from_token), db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(WorkerModel.model_name).where(WorkerModel.worker_id == worker.id))
    models = [r[0] for r in res.all()]
    return WorkerPublic(
        id=worker.id,
        username=worker.username,
        display_name=worker.display_name,
        status=worker.status.value,
        skills=worker.skills or [],
        earnings_cents=worker.earnings_cents,
        current_task_id=worker.current_task_id,
        served_models=models,
    )


@router.get("/worker/tasks")
async def worker_tasks(worker: Worker = Depends(get_worker_from_token), db: AsyncSession = Depends(get_session)):
    # Pending tasks the worker could grab (from the model pool) + the worker's active task.
    # Read from the DB directly (not the in-memory broker queue) so pending
    # tasks survive service restarts.
    served = await _served_models(db, worker.id)
    pending = []
    if served:
        res = await db.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.pending,
                Task.model.in_(served),
                Task.assigned_worker_id.is_(None),
            )
            .order_by(Task.created_at.asc())
        )
        for t in res.scalars().all():
            pending.append({"id": t.id, "model": t.model, "status": t.status.value, "preview": _preview(t)})
    active = None
    if worker.current_task_id:
        t = await db.get(Task, worker.current_task_id)
        if t and t.status in (TaskStatus.assigned, TaskStatus.streaming):
            active = {"id": t.id, "model": t.model, "status": t.status.value}
    return {"pending": pending, "active": active}


async def _served_models(db: AsyncSession, worker_id: int) -> list[str]:
    res = await db.execute(select(WorkerModel.model_name).where(WorkerModel.worker_id == worker_id))
    return [r[0] for r in res.all()]


def _preview(task: Task) -> str:
    for m in task.messages:
        c = m.get("content")
        if isinstance(c, str):
            return c[:120]
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text":
                    return p.get("text", "")[:120]
    return ""


# ------------------------------ WebSocket ------------------------------
@ws_router.websocket("/ws/worker")
async def ws_worker(websocket: WebSocket):
    await websocket.accept()
    token = websocket.query_params.get("token") or ""
    if not token:
        auth = websocket.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "") if auth.lower().startswith("bearer ") else auth
    payload = decode_access_token(token)
    if not payload or payload.get("sub") is None:
        await websocket.close(code=4401)
        return
    async with AsyncSessionLocal() as db:
        if payload.get("role") == "worker":
            worker = await db.get(Worker, int(payload["sub"]))
        else:
            # super_admin / staff / legacy admin: resolve their bound worker
            result = await db.execute(select(Worker).where(Worker.owner_user_id == int(payload["sub"])))
            worker = result.scalar_one_or_none()
        if worker is None or not worker.is_active:
            await websocket.close(code=4404)
            return
        worker_id = worker.id
        worker.status = WorkerStatus.online
        prev_task_id = worker.current_task_id
        worker.current_task_id = None
        await db.commit()
        if prev_task_id:
            await _resend_task(db, prev_task_id, worker_id)

    broker.add_worker(worker_id)
    out = broker.out_queue(worker_id)

    # Re-dispatch: when a worker comes online, auto-assign any pending tasks
    # in the model pools this worker serves (up to the model concurrency).
    await _auto_take_pending(worker_id)

    async def sender():
        while True:
            msg = await out.get()
            await websocket.send_json(msg)

    async def receiver():
        while True:
            data = await websocket.receive_json()
            await _handle_message(worker_id, data)

    try:
        await asyncio.gather(sender(), receiver())
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        import logging as _log
        _log.exception("worker ws loop error: %s", exc)
    finally:
        broker.remove_worker(worker_id)
        async with AsyncSessionLocal() as db:
            w = await db.get(Worker, worker_id)
            if w is not None:
                w.status = WorkerStatus.offline
                if w.current_task_id:
                    await _reassign_on_disconnect(db, w)
                else:
                    w.current_task_id = None
                await db.commit()


async def _resend_task(db: AsyncSession, task_id: str, worker_id: int) -> None:
    task = await db.get(Task, task_id)
    if task and task.status in (TaskStatus.assigned, TaskStatus.streaming):
        res = await db.execute(select(Attachment).where(Attachment.task_id == task.id))
        attachments = [
            {"id": a.id, "kind": a.kind, "url": a.url, "filename": a.filename, "content_type": a.content_type}
            for a in res.scalars().all()
        ]
        broker.send_to_worker(
            worker_id,
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


async def _auto_take_pending(worker_id: int) -> None:
    """When a worker connects, immediately grab pending tasks from the model
    pools it serves. This closes the gap where tasks were created while the
    worker was offline (they sit 'pending' forever otherwise). Reads the DB
    directly (not the in-memory broker queue) so tasks that pre-date a service
    restart are picked up too."""
    async with AsyncSessionLocal() as db:
        worker = await db.get(Worker, worker_id)
        if worker is None or not worker.is_active:
            return
        # Reclaim stale assignments: tasks this worker owns but which have
        # not been touched since their model's timeout are treated as orphans
        # (a previous WS session died mid-task). Requeue them so they can be
        # picked up again instead of occupying concurrency slots forever.
        stale = (
            await db.execute(
                select(Task).where(
                    Task.assigned_worker_id == worker_id,
                    Task.status.in_([TaskStatus.assigned, TaskStatus.streaming]),
                    Task.assigned_at.isnot(None),
                )
            )
        ).scalars().all()
        for t in stale:
            model_cfg = (
                await db.execute(select(ModelConfig).where(ModelConfig.name == t.model))
            ).scalar_one_or_none()
            timeout_s = model_cfg.timeout_seconds if model_cfg else settings.TASK_TIMEOUT_SECONDS
            if t.assigned_at and (datetime.utcnow() - t.assigned_at).total_seconds() > timeout_s:
                t.assigned_worker_id = None
                t.status = TaskStatus.pending
                t.assigned_at = None
                await broker.enqueue_pending(t.model, t.id)
        await db.commit()
        served = await _served_models(db, worker_id)
        if not served:
            return
        # Batch-fetch model configs for served models (avoid N+1 queries).
        model_cfg_by_name = {
            mc.name: mc
            for mc in (await db.execute(
                select(ModelConfig).where(ModelConfig.name.in_(served))
            )).scalars().all()
        }
        # Batch-count this worker's active tasks per model (one query).
        active_rows = (
            await db.execute(
                select(Task.model, func.count())
                .where(
                    Task.assigned_worker_id == worker_id,
                    Task.status.in_([TaskStatus.assigned, TaskStatus.streaming]),
                )
                .group_by(Task.model)
            )
        ).all()
        active_by_model = {m: c for m, c in active_rows}

        res = await db.execute(
            select(Task)
            .where(
                Task.status == TaskStatus.pending,
                Task.model.in_(served),
                Task.assigned_worker_id.is_(None),
            )
            .order_by(Task.created_at.asc())
        )
        for task in res.scalars().all():
            model_cfg = model_cfg_by_name.get(task.model)
            if model_cfg is None or not model_cfg.is_active:
                continue
            # Respect concurrency: only take tasks while this worker has free
            # slots for THIS model (other models have their own slots).
            if active_by_model.get(task.model, 0) >= model_cfg.concurrency:
                continue
            await assign_to_worker(db, task, worker, model_cfg)
            active_by_model[task.model] = active_by_model.get(task.model, 0) + 1
            await asyncio.sleep(0.05)  # let the assignment settle


async def _handle_message(worker_id: int, data: dict) -> None:
    mtype = data.get("type")
    if mtype == "heartbeat":
        broker.send_to_worker(worker_id, {"type": "pong"})
        return
    if mtype == "grab":
        await _grab(worker_id, data.get("task_id"))
        return
    if mtype == "chunk":
        await _chunk(worker_id, data.get("task_id"), data.get("text", ""))
        return
    if mtype == "done":
        await _done(
            worker_id,
            data.get("task_id"),
            data.get("text"),
            data.get("tool_calls"),
        )
        return
    if mtype == "cancel":
        await _cancel(worker_id, data.get("task_id"))
        return


async def _grab(worker_id: int, task_id: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.status != TaskStatus.pending:
            return
        serves = (await db.execute(
            select(WorkerModel).where(
                WorkerModel.worker_id == worker_id, WorkerModel.model_name == task.model
            )
        )).scalar_one_or_none()
        if serves is None:
            broker.send_to_worker(worker_id, {"type": "error", "message": "You are not in this model's pool."})
            return
        worker = await db.get(Worker, worker_id)
        model_cfg = (await db.execute(
            select(ModelConfig).where(ModelConfig.name == task.model)
        )).scalar_one_or_none()
        # Concurrency is counted per model, so tasks from other models do not
        # consume this model's slots.
        active = (await db.execute(
            select(Task).where(
                Task.assigned_worker_id == worker_id,
                Task.model == task.model,
                Task.status.in_([TaskStatus.assigned, TaskStatus.streaming]),
            )
        )).scalars().all()
        if len(active) >= (model_cfg.concurrency if model_cfg else 1):
            broker.send_to_worker(worker_id, {"type": "error", "message": "Concurrency limit reached."})
            return
        await assign_to_worker(db, task, worker, model_cfg)


async def _chunk(worker_id: int, task_id: str, text: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.assigned_worker_id != worker_id:
            return
        if task.status in (TaskStatus.completed, TaskStatus.cancelled, TaskStatus.timeout):
            return
        task.reply_text = (task.reply_text or "") + text
        if task.status == TaskStatus.assigned:
            task.status = TaskStatus.streaming
        await db.commit()
    import logging as _log
    _log.info("CHUNK published for %s", task_id)
    broker.publish_event(task_id, {"type": "chunk", "text": text})


async def _done(
    worker_id: int,
    task_id: str,
    text: str | None,
    tool_calls: list[dict] | None = None,
) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.assigned_worker_id != worker_id:
            return
        if task.status in (TaskStatus.completed, TaskStatus.cancelled, TaskStatus.timeout):
            return
        if text is not None and text != "":
            task.reply_text = text
        worker = await db.get(Worker, worker_id)
        if tool_calls:
            from app.tools import BUILTIN_TOOLS, execute_tool_call

            call_names = {c.get("function", {}).get("name") for c in tool_calls if isinstance(c, dict)}
            builtin_only = bool(call_names) and call_names.issubset(set(BUILTIN_TOOLS.keys()))

            if builtin_only:
                # Built-in tools (run_shell): the server executes them right
                # here, appends the tool-result messages, and re-dispatches to
                # the same worker so the conversation continues in one window.
                msgs = list(task.messages or [])
                msgs.append({"role": "assistant", "content": text, "tool_calls": tool_calls})
                for call in tool_calls:
                    result = await execute_tool_call(call)
                    msgs.append(
                        {"role": "tool", "tool_call_id": call.get("id"), "content": result}
                    )
                task.messages = msgs
                task.reply_text = ""
                task.tool_calls = None
                task.finish_reason = None
                model_cfg = (
                    await db.execute(select(ModelConfig).where(ModelConfig.name == task.model))
                ).scalar_one_or_none()
                task.status = TaskStatus.assigned
                task.assigned_at = datetime.utcnow()
                task.timeout_at = datetime.utcnow() + timedelta(
                    seconds=model_cfg.timeout_seconds if model_cfg else 600
                )
                worker.status = WorkerStatus.busy
                worker.current_task_id = task.id
                await db.commit()
                # Re-push the updated conversation to the worker's WS.
                await _resend_task(db, task.id, worker_id)
                return
            # External tool (the caller must execute): return tool_calls and
            # keep the task alive in waiting_tool. The caller runs the tools and
            # sends back results in a follow-up request (matched by session_id),
            # which continues the SAME task.
            task.finish_reason = "tool_calls"
            task.tool_calls = tool_calls
            task.status = TaskStatus.waiting_tool
            task.completed_at = None
            worker.status = WorkerStatus.online
            worker.current_task_id = None
            await db.commit()
            usage = {
                "prompt_tokens": max(1, (sum_prompt_chars(task.messages) or 0) // 4),
                "completion_tokens": 0,
                "total_tokens": max(1, (sum_prompt_chars(task.messages) or 0) // 4),
            }
            payload: dict = {
                "type": "done",
                "usage": usage,
                "text": task.reply_text,
                "tool_calls": tool_calls,
                "finish_reason": "tool_calls",
            }
            broker.publish_event(task_id, payload)
            return
        # Normal completion: settle billing, finish the conversation.
        task.status = TaskStatus.completed
        task.completed_at = datetime.utcnow()
        task.finish_reason = "stop"
        worker.status = WorkerStatus.online
        worker.current_task_id = None
        model_cfg = (await db.execute(
            select(ModelConfig).where(ModelConfig.name == task.model)
        )).scalar_one_or_none()
        usage = await settle(db, task, model_cfg, worker, task.precharge_cents, settings.COMMISSION_RATE)
    import logging as _log
    _log.info("DONE published for %s usage=%s", task_id, usage)
    payload = {"type": "done", "usage": usage, "text": task.reply_text}
    broker.publish_event(task_id, payload)


async def _cancel(worker_id: int, task_id: str) -> None:
    async with AsyncSessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None or task.assigned_worker_id != worker_id:
            return
        if task.status in (TaskStatus.completed, TaskStatus.cancelled, TaskStatus.timeout):
            return
        task.status = TaskStatus.cancelled
        worker = await db.get(Worker, worker_id)
        worker.status = WorkerStatus.online
        worker.current_task_id = None
        user = await db.get(User, task.user_id) if task.user_id else None
        if user is not None and task.precharge_cents:
            user.balance_cents += task.precharge_cents
            db.add(Transaction(task_id=task.id, kind=TransactionKind.refund, user_id=user.id,
                               amount_cents=task.precharge_cents, note="refund on cancel"))
        await db.commit()
    broker.publish_event(task_id, {"type": "cancelled"})


async def _reassign_on_disconnect(db: AsyncSession, worker: Worker) -> None:
    task = await db.get(Task, worker.current_task_id)
    worker.current_task_id = None
    if task and task.status in (TaskStatus.assigned, TaskStatus.streaming):
        task.assigned_worker_id = None
        task.status = TaskStatus.pending
        task.assigned_at = None
        await db.commit()
        from app.dispatch import enqueue_for_grab

        await enqueue_for_grab(db, task)
        if settings.AUTO_ASSIGN:
            model_cfg = (await db.execute(
                select(ModelConfig).where(ModelConfig.name == task.model)
            )).scalar_one_or_none()
            if model_cfg:
                from app.dispatch import auto_assign

                await auto_assign(db, task, model_cfg)

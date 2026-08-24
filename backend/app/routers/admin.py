"""Admin management API: users, workers, models, API keys, tasks, usage, logs.

Permission model: the router requires an authenticated dashboard user. Each
module route additionally gates on a permission bit (require_permission). User
management itself is reserved for super_admin (require_super_admin).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.broker import broker
from app.deps import get_current_user, require_permission, require_super_admin
from app.models import (
    ALL_PERMISSIONS,
    ApiKey,
    EventLog,
    ModelConfig,
    Task,
    TaskStatus,
    Transaction,
    TransactionKind,
    User,
    UserRole,
    Worker,
    WorkerModel,
    WorkerStatus,
)
from app.schemas import (
    ApiKeyCreated,
    ApiKeyCreate,
    ModelCreate,
    ModelPublic,
    StatsResponse,
    TaskPublic,
    UserCreate,
    UserPublic,
    UserUpdate,
    WorkerPublic,
)
from app.security import (
    generate_api_key,
    hash_api_key,
    hash_password,
    validate_password_strength,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(get_current_user)])


def _serialize_user(u: User, worker: Worker | None) -> UserPublic:
    return UserPublic(
        id=u.id,
        username=u.username,
        email=u.email,
        role=u.role.value,
        permissions=u.permissions,
        is_active=u.is_active,
        balance_cents=u.balance_cents,
        created_at=u.created_at,
        worker_status=worker.status.value if worker else None,
        worker_id=worker.id if worker else None,
    )


async def _get_user_worker(db: AsyncSession, user_id: int) -> Worker | None:
    return (
        await db.execute(select(Worker).where(Worker.owner_user_id == user_id))
    ).scalar_one_or_none()


# ------------------------------ users (super admin only) ------------------------------
@router.get("/users", response_model=list[UserPublic])
async def list_users(
    _=Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    res = await db.execute(select(User).order_by(User.id))
    out = []
    for u in res.scalars().all():
        out.append(_serialize_user(u, await _get_user_worker(db, u.id)))
    return out


@router.post("/users", response_model=UserPublic)
async def create_user(
    body: UserCreate,
    _=Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    if await db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(400, "Username already exists.")
    pw_errors = validate_password_strength(body.password)
    if pw_errors:
        raise HTTPException(400, "密码不满足安全策略：" + "；".join(pw_errors))
    if body.role == "super_admin":
        role = UserRole.super_admin
        perms = None
    else:
        role = UserRole.staff
        perms = [p for p in (body.permissions or []) if p in ALL_PERMISSIONS]
    u = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
        role=role,
        permissions=perms,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    # Every dashboard user owns a bound worker so they can take orders on the
    # workbench WebSocket. Bind it to every active model.
    worker = Worker(
        username=f"{u.username}-worker",
        display_name=f"{u.username} (you)",
        hashed_password=hash_password(body.password),
        owner_user_id=u.id,
        status=WorkerStatus.offline,
        skills=["general", "multimodal"],
    )
    db.add(worker)
    await db.flush()
    res = await db.execute(select(ModelConfig.name).where(ModelConfig.is_active == True))  # noqa: E712
    for (name,) in res.all():
        db.add(WorkerModel(worker_id=worker.id, model_name=name))
    await db.commit()
    return _serialize_user(u, worker)


@router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(
    user_id: int,
    body: UserUpdate,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if body.role is not None:
        new_role = UserRole.super_admin if body.role == "super_admin" else UserRole.staff
        if u.id == actor.id and new_role != UserRole.super_admin:
            raise HTTPException(400, "You cannot demote yourself.")
        u.role = new_role
        if new_role == UserRole.super_admin:
            u.permissions = None
    if body.permissions is not None:
        u.permissions = (
            [p for p in body.permissions if p in ALL_PERMISSIONS] if u.role == UserRole.staff else None
        )
    if body.is_active is not None:
        if u.id == actor.id and not body.is_active:
            raise HTTPException(400, "You cannot deactivate yourself.")
        # Prevent deactivating the last super admin.
        if u.role == UserRole.super_admin and not body.is_active:
            cnt = (
                await db.execute(
                    select(func.count())
                    .select_from(User)
                    .where(User.role == UserRole.super_admin, User.is_active == True)  # noqa: E712
                )
            ).scalar() or 0
            if cnt <= 1:
                raise HTTPException(400, "Cannot deactivate the last super admin.")
        u.is_active = body.is_active
    if body.password:
        pw_errors = validate_password_strength(body.password)
        if pw_errors:
            raise HTTPException(400, "密码不满足安全策略：" + "；".join(pw_errors))
        u.hashed_password = hash_password(body.password)
        # Changing the password revokes all previously issued JWTs.
        u.token_version = (u.token_version or 0) + 1
    if body.email is not None:
        u.email = body.email
    await db.commit()
    return _serialize_user(u, await _get_user_worker(db, u.id))


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == actor.id:
        raise HTTPException(400, "You cannot delete yourself.")
    if u.role == UserRole.super_admin:
        cnt = (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.role == UserRole.super_admin, User.is_active == True)  # noqa: E712
            )
        ).scalar() or 0
        if cnt <= 1:
            raise HTTPException(400, "Cannot delete the last super admin.")
    # Explicitly remove the user's bound worker and API keys (the SQLite FK
    # cascade may not run if PRAGMA foreign_keys is off), then delete the user.
    worker = await _get_user_worker(db, u.id)
    if worker is not None:
        await db.delete(worker)
    for key in (
        (await db.execute(select(ApiKey).where(ApiKey.user_id == u.id))).scalars().all()
    ):
        await db.delete(key)
    await db.delete(u)
    await db.commit()
    return {"deleted": user_id}


@router.get("/users/{user_id}/earnings")
async def user_earnings(
    user_id: int,
    _=Depends(require_super_admin),
    db: AsyncSession = Depends(get_session),
):
    """该用户作为接单账号收到的收益明细（worker_earning 流水）与汇总。"""
    u = await db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    res = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.kind == TransactionKind.worker_earning)
        .order_by(Transaction.created_at.desc())
    )
    rows = res.scalars().all()
    total = sum((t.amount_cents for t in rows), 0)
    return {
        "user_id": user_id,
        "username": u.username,
        "total_cents": total,
        "count": len(rows),
        "items": [
            {
                "id": t.id,
                "task_id": t.task_id,
                "amount_cents": t.amount_cents,
                "note": t.note,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
    }


# ------------------------------ stats ------------------------------
@router.get("/stats", response_model=StatsResponse)
async def stats(_=Depends(require_permission("overview_view")), db: AsyncSession = Depends(get_session)):
    def _c(expr):
        return func.count().filter(expr)

    users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    workers = (await db.execute(select(func.count()).select_from(Worker))).scalar() or 0
    workers_online = (
        await db.execute(
            select(func.count()).select_from(Worker).where(Worker.status == WorkerStatus.online)
        )
    ).scalar() or 0
    models = (await db.execute(select(func.count()).select_from(ModelConfig))).scalar() or 0
    tasks_total = (await db.execute(select(func.count()).select_from(Task))).scalar() or 0
    tasks_completed = (
        await db.execute(select(func.count()).select_from(Task).where(Task.status == TaskStatus.completed))
    ).scalar() or 0
    tasks_pending = (
        await db.execute(
            select(func.count()).select_from(Task).where(Task.status.in_([TaskStatus.pending, TaskStatus.assigned, TaskStatus.streaming]))
        )
    ).scalar() or 0
    revenue = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.kind == TransactionKind.platform_commission
            )
        )
    ).scalar() or 0
    payouts = (
        await db.execute(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                Transaction.kind == TransactionKind.worker_earning
            )
        )
    ).scalar() or 0
    commission = revenue
    return StatsResponse(
        users=users,
        workers=workers,
        workers_online=workers_online,
        models=models,
        tasks_total=tasks_total,
        tasks_completed=tasks_completed,
        tasks_pending=tasks_pending,
        revenue_cents=commission,
        worker_payouts_cents=payouts,
        platform_commission_cents=commission,
    )


@router.get("/calls-trend")
async def calls_trend(
    days: int = Query(14, ge=1, le=90),
    _=Depends(require_permission("overview_view")),
    db: AsyncSession = Depends(get_session),
):
    """最近 N 天每天的任务（调用）数量，按天补齐（无调用记为 0）。"""
    today = date.today()
    res = await db.execute(
        select(func.date(Task.created_at), func.count())
        .where(Task.created_at >= today - timedelta(days=days - 1))
        .group_by(func.date(Task.created_at))
    )
    counts = {row[0]: row[1] for row in res.all()}
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        out.append({"date": d.strftime("%m-%d"), "count": int(counts.get(key, 0))})
    return out


# ------------------------------ workers ------------------------------
@router.get("/workers", response_model=list[WorkerPublic])
async def list_workers(_=Depends(require_permission("workbench")), db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(Worker).order_by(Worker.id))
    rows = res.scalars().all()
    out = []
    for w in rows:
        res2 = await db.execute(select(WorkerModel.model_name).where(WorkerModel.worker_id == w.id))
        models = [r[0] for r in res2.all()]
        owner_name = None
        if w.owner_user_id:
            owner_name = await db.scalar(select(User.username).where(User.id == w.owner_user_id))
        out.append(WorkerPublic(id=w.id, username=w.username, display_name=w.display_name,
                               status=w.status.value, skills=w.skills or [], earnings_cents=w.earnings_cents,
                               current_task_id=w.current_task_id, served_models=models,
                               owner_username=owner_name, owner_id=w.owner_user_id))
    return out


@router.post("/workers", response_model=WorkerPublic)
async def create_worker(username: str, password: str, display_name: str = "", skills: str = "",
                        db: AsyncSession = Depends(get_session)):
    if await db.scalar(select(Worker.id).where(Worker.username == username)):
        raise HTTPException(400, "Username already taken.")
    w = Worker(username=username, display_name=display_name or username,
               hashed_password=hash_password(password), status=WorkerStatus.offline,
               skills=[s.strip() for s in skills.split(",") if s.strip()])
    db.add(w)
    await db.flush()
    res = await db.execute(select(ModelConfig.name).where(ModelConfig.is_active == True))  # noqa: E712
    for (name,) in res.all():
        db.add(WorkerModel(worker_id=w.id, model_name=name))
    await db.commit()
    return WorkerPublic(id=w.id, username=w.username, display_name=w.display_name, status=w.status.value,
                        skills=w.skills or [], earnings_cents=0, current_task_id=None, served_models=[])


# ------------------------------ models ------------------------------
@router.get("/models", response_model=list[ModelPublic])
async def list_models_admin(_=Depends(require_permission("models_view")), db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(ModelConfig).order_by(ModelConfig.id))
    rows = res.scalars().all()
    out = []
    for m in rows:
        res2 = await db.execute(select(WorkerModel.worker_id).where(WorkerModel.model_name == m.name))
        wids = [r[0] for r in res2.all()]
        workers = []
        if wids:
            res3 = await db.execute(select(Worker.username).where(Worker.id.in_(wids)))
            workers = [r[0] for r in res3.all()]
        out.append(ModelPublic(id=m.id, name=m.name, display_name=m.display_name, description=m.description,
                               price_per_request_cents=m.price_per_request_cents,
                               price_per_1k_chars_cents=m.price_per_1k_chars_cents,
                               price_per_minute_cents=m.price_per_minute_cents, concurrency=m.concurrency,
                               timeout_seconds=m.timeout_seconds, is_active=m.is_active, created_at=m.created_at,
                               worker_usernames=workers))
    return out


@router.post("/models", response_model=ModelPublic)
async def create_model(body: ModelCreate, _=Depends(require_permission("models_manage")),
                       db: AsyncSession = Depends(get_session)):
    if await db.scalar(select(ModelConfig.id).where(ModelConfig.name == body.name)):
        raise HTTPException(400, "Model name already exists.")
    m = ModelConfig(
        name=body.name, display_name=body.display_name or body.name, description=body.description or "",
        price_per_request_cents=body.price_per_request_cents, price_per_1k_chars_cents=body.price_per_1k_chars_cents,
        price_per_minute_cents=body.price_per_minute_cents, concurrency=body.concurrency,
        timeout_seconds=body.timeout_seconds, is_active=body.is_active,
    )
    db.add(m)
    await db.flush()
    for uname in body.worker_usernames:
        w = (await db.execute(select(Worker).where(Worker.username == uname))).scalar_one_or_none()
        if w:
            db.add(WorkerModel(worker_id=w.id, model_name=m.name))
    await db.commit()
    await db.refresh(m)
    return ModelPublic(id=m.id, name=m.name, display_name=m.display_name, description=m.description,
                       price_per_request_cents=m.price_per_request_cents,
                       price_per_1k_chars_cents=m.price_per_1k_chars_cents,
                       price_per_minute_cents=m.price_per_minute_cents, concurrency=m.concurrency,
                       timeout_seconds=m.timeout_seconds, is_active=m.is_active, created_at=m.created_at,
                       worker_usernames=body.worker_usernames)


@router.patch("/models/{name}")
async def update_model(name: str, is_active: bool | None = None, concurrency: int | None = None,
                       _=Depends(require_permission("models_manage")), db: AsyncSession = Depends(get_session)):
    m = (await db.execute(select(ModelConfig).where(ModelConfig.name == name))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Model not found")
    if is_active is not None:
        m.is_active = is_active
    if concurrency is not None:
        m.concurrency = concurrency
    await db.commit()
    return {"name": name, "is_active": m.is_active, "concurrency": m.concurrency}


@router.delete("/models/{name}")
async def delete_model(name: str, _=Depends(require_permission("models_manage")),
                       db: AsyncSession = Depends(get_session)):
    m = (await db.execute(select(ModelConfig).where(ModelConfig.name == name))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "Model not found")
    await db.execute(select(WorkerModel).where(WorkerModel.model_name == name))  # touch for FK
    await db.delete(m)
    await db.commit()
    return {"deleted": name}


# ------------------------------ api keys ------------------------------
@router.get("/apikeys")
async def list_apikeys(_=Depends(require_permission("apikeys_view")), db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(ApiKey).order_by(ApiKey.id))
    return [
        {"id": k.id, "name": k.name, "key_prefix": k.key_prefix, "full_key": k.full_key,
         "user_id": k.user_id, "is_active": k.is_active, "last_used_at": k.last_used_at,
         "created_at": k.created_at}
        for k in res.scalars().all()
    ]


@router.post("/apikeys", response_model=ApiKeyCreated)
async def create_apikey_for_user(
    body: ApiKeyCreate,
    user=Depends(require_permission("apikeys_manage")),
    db: AsyncSession = Depends(get_session),
):
    key, prefix = generate_api_key()
    rec = ApiKey(
        key_prefix=prefix,
        key_hash=hash_api_key(key),
        full_key=key,
        user_id=user.id,
        name=body.name,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return ApiKeyCreated(id=rec.id, name=rec.name, key=key, key_prefix=prefix)


@router.delete("/apikeys/{key_id}")
async def delete_apikey(key_id: int, _=Depends(require_permission("apikeys_manage")),
                        db: AsyncSession = Depends(get_session)):
    k = await db.get(ApiKey, key_id)
    if k is None:
        raise HTTPException(404, "API key not found")
    await db.delete(k)
    await db.commit()
    return {"deleted": key_id}


# ------------------------------ tasks ------------------------------
@router.get("/tasks", response_model=list[TaskPublic])
async def list_tasks(limit: int = Query(50, le=200), _=Depends(require_permission("tasks_view")),
                     db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(Task).order_by(Task.created_at.desc()).limit(limit))
    return [
        TaskPublic(id=t.id, model=t.model, user_id=t.user_id, api_key_id=t.api_key_id, status=t.status.value,
                   stream=t.stream, reply_text=(t.reply_text or "")[:500], usage=t.usage, error=t.error,
                   finish_reason=t.finish_reason, created_at=t.created_at, assigned_at=t.assigned_at,
                   completed_at=t.completed_at, assigned_worker_id=t.assigned_worker_id)
        for t in res.scalars().all()
    ]


@router.post("/tasks/{task_id}/cancel", response_model=TaskPublic)
async def cancel_task(
    task_id: str,
    _=Depends(require_permission("tasks_manage")),
    db: AsyncSession = Depends(get_session),
):
    """Cancel a task that has not finished yet (pending / assigned / waiting_tool).

    Refunds the pre-charged balance for unpaid tasks and notifies the worker
    if one is currently attached. Terminal tasks (completed/failed/cancelled/
    timeout) are rejected so the action stays idempotent-safe.
    """
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if task.status in (
        TaskStatus.completed, TaskStatus.failed,
        TaskStatus.cancelled, TaskStatus.timeout,
    ):
        raise HTTPException(409, f"Task already in terminal state: {task.status.value}")
    # Refund any pre-charge that hasn't been settled yet.
    if task.precharge_cents:
        user = await db.get(User, task.user_id) if task.user_id else None
        if user is not None:
            user.balance_cents += task.precharge_cents
            db.add(Transaction(
                task_id=task.id, kind=TransactionKind.refund,
                user_id=user.id, amount_cents=task.precharge_cents,
                note="refund on admin cancel",
            ))
    task.status = TaskStatus.cancelled
    task.completed_at = datetime.utcnow()
    task.assigned_worker_id = None
    task.assigned_at = None
    await db.commit()
    # If a worker holds it, tell them it was cancelled (so their WS updates).
    if task.assigned_worker_id is not None:
        broker.publish_event(task_id, {"type": "cancelled"})
    broker.remove_pending(task.model, task_id)
    return TaskPublic(
        id=task.id, model=task.model, user_id=task.user_id, api_key_id=task.api_key_id,
        status=task.status.value, stream= (task.stream or False), reply_text=task.reply_text or "",
        usage=task.usage, error=task.error, finish_reason=task.finish_reason,
        created_at=task.created_at, assigned_at=task.assigned_at,
        completed_at=task.completed_at, assigned_worker_id=task.assigned_worker_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskPublic)
async def get_task(task_id: str, _=Depends(require_permission("tasks_view")),
                   db: AsyncSession = Depends(get_session)):
    t = await db.get(Task, task_id)
    if t is None:
        raise HTTPException(404, "Task not found")
    return TaskPublic(id=t.id, model=t.model, user_id=t.user_id, api_key_id=t.api_key_id, status=t.status.value,
                      stream=t.stream, reply_text=t.reply_text or "", usage=t.usage, error=t.error,
                      finish_reason=t.finish_reason, created_at=t.created_at, assigned_at=t.assigned_at,
                      completed_at=t.completed_at, assigned_worker_id=t.assigned_worker_id)


# ------------------------------ usage & logs ------------------------------
@router.get("/usage")
async def usage(_=Depends(require_permission("usage_view")), db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(Transaction).order_by(Transaction.created_at.desc()).limit(100))
    rows = res.scalars().all()
    return [
        {"id": t.id, "kind": t.kind.value, "task_id": t.task_id, "user_id": t.user_id,
         "worker_id": t.worker_id, "amount_cents": t.amount_cents, "note": t.note,
         "created_at": t.created_at.isoformat() if t.created_at else None}
        for t in rows
    ]


@router.get("/logs")
async def logs(limit: int = Query(100, le=500), _=Depends(require_permission("logs_view")),
               db: AsyncSession = Depends(get_session)):
    res = await db.execute(select(EventLog).order_by(EventLog.created_at.desc()).limit(limit))
    return [
        {"id": l.id, "kind": l.kind, "actor": l.actor, "task_id": l.task_id,
         "detail": l.detail, "created_at": l.created_at.isoformat() if l.created_at else None}
        for l in res.scalars().all()
    ]

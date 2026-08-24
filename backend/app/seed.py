"""First-boot seeding: the single administrator (who is also the only human
worker) and the default model pool. Idempotent — safe to call on every startup.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    ModelConfig,
    User,
    UserRole,
    Worker,
    WorkerModel,
    WorkerStatus,
)
from app.security import hash_password

DEFAULT_MODELS = [
    {
        "name": "human-default",
        "display_name": "Human Default",
        "description": "A general-purpose human answers your prompt.",
        "price_per_request_cents": 5,
        "price_per_1k_chars_cents": 1,
        "price_per_minute_cents": 10,
        "concurrency": 2,
        "timeout_seconds": 600,
    },
    {
        "name": "human-fast",
        "display_name": "Human Fast",
        "description": "Fast human turnaround for short tasks.",
        "price_per_request_cents": 2,
        "price_per_1k_chars_cents": 0,
        "price_per_minute_cents": 5,
        "concurrency": 4,
        "timeout_seconds": 120,
    },
    {
        "name": "human-expert",
        "display_name": "Human Expert",
        "description": "Senior human expert for complex prompts.",
        "price_per_request_cents": 20,
        "price_per_1k_chars_cents": 5,
        "price_per_minute_cents": 50,
        "concurrency": 1,
        "timeout_seconds": 1800,
    },
    {
        "name": "human-cn",
        "display_name": "人类中文",
        "description": "中文母语真人回复。",
        "price_per_request_cents": 5,
        "price_per_1k_chars_cents": 1,
        "price_per_minute_cents": 10,
        "concurrency": 2,
        "timeout_seconds": 600,
    },
    {
        "name": "human-en",
        "display_name": "Human English",
        "description": "Native English human replies.",
        "price_per_request_cents": 5,
        "price_per_1k_chars_cents": 1,
        "price_per_minute_cents": 10,
        "concurrency": 2,
        "timeout_seconds": 600,
    },
]


async def seed_initial(db: AsyncSession) -> dict:
    created = {"models": 0, "admin": False, "worker": False}

    # Models
    for m in DEFAULT_MODELS:
        exists = await db.scalar(select(ModelConfig.id).where(ModelConfig.name == m["name"]))
        if not exists:
            db.add(ModelConfig(**m))
            created["models"] += 1

    # Admin — the super_admin account. Also the first human worker.
    # Starts with a generous balance so its own API-key calls can clear the
    # pre-charge (the admin is both caller and worker in single-account use).
    admin = await db.scalar(
        select(User).where(User.role.in_([UserRole.super_admin]))
    )
    if admin is None:
        admin = User(
            username=settings.DEFAULT_ADMIN_USERNAME,
            email=settings.DEFAULT_ADMIN_EMAIL,
            hashed_password=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            role=UserRole.super_admin,
            permissions=None,  # full access
            balance_cents=1_000_00,
        )
        db.add(admin)
        await db.flush()
        created["admin"] = True
    else:
        await db.flush()

    # Built-in worker owned by the admin: the admin IS the human model.
    worker = await db.scalar(select(Worker).where(Worker.owner_user_id == admin.id))
    if worker is None:
        worker = Worker(
            username=f"{admin.username}-worker",
            display_name=f"{admin.username} (you)",
            hashed_password=hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            owner_user_id=admin.id,
            status=WorkerStatus.offline,
            skills=["general", "multimodal"],
        )
        db.add(worker)
        await db.flush()
        for m in DEFAULT_MODELS:
            db.add(WorkerModel(worker_id=worker.id, model_name=m["name"]))
        created["worker"] = True

    await db.commit()
    return created

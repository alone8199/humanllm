"""GET /v1/models — OpenAI-compatible model listing."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ModelConfig
from app.schemas import ModelInfo

router = APIRouter()


@router.get("/v1/models")
async def list_models(db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(ModelConfig).where(ModelConfig.is_active == True))  # noqa: E712
    models = result.scalars().all()
    data = [
        ModelInfo(
            id=m.name,
            created=int(time.time()),
            display_name=m.display_name,
            description=m.description,
            pricing={
                "per_request_cents": m.price_per_request_cents,
                "per_1k_chars_cents": m.price_per_1k_chars_cents,
                "per_minute_cents": m.price_per_minute_cents,
                "concurrency": m.concurrency,
                "timeout_seconds": m.timeout_seconds,
            },
        )
        for m in models
    ]
    return {"object": "list", "data": [d.model_dump() for d in data]}

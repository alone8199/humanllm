"""OpenAI-compatible chat completions HTTP endpoint.

The router handles HTTP concerns only. Chat task lifecycle and domain behavior
live in ``app.services``.
No AI model is ever contacted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.deps import authenticate_api_key
from app.models import ModelConfig, User
from app.openai_errors import OpenAIError
from app.ratelimit import limiter
from app.schemas import ChatCompletionRequest
from app.services.chat import (
    collect_task,
    off_hours_active,
    off_hours_response,
    stream_task,
)
from app.services.task_flow import create_or_continue_task, dispatch_task

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    api_key=Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_session),
):
    """Create or continue a human-response task and expose its result."""
    if settings.RATE_LIMIT_ENABLED:
        allowed, _rem, _retry_after = limiter.check(
            f"chat:key:{api_key.id}", settings.RATE_APIKEY_CHAT_PER_MIN, 60
        )
        if not allowed:
            raise OpenAIError(
                "Rate limit exceeded for this API key. Slow down and retry later.",
                status_code=429,
                error_type="rate_limit_error",
                code="rate_limited",
            )

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

    task = await create_or_continue_task(db, req, api_key, user, model_cfg)
    await dispatch_task(db, task, model_cfg)

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

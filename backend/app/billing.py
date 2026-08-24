"""Billing: estimate hold, compute usage, settle user/worker/platform accounts.

NOTE: There is no AI model here, so "tokens" are estimated as characters / 4
(a common heuristic) purely so the OpenAI-compatible `usage` object has the
expected shape. Real billing is driven by characters and wall-clock time as
configured per model. All money is handled in integer cents to avoid floats.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelConfig, Task, Transaction, TransactionKind, User, Worker
from app.openai_errors import OpenAIError

# Guards so a worker cannot produce output that exceeds the reserved hold.
MAX_CHARS_CAP = 200_000
PRECHARGE_CHARS_FLOOR = 4_000
PRECHARGE_CHARS_FACTOR = 10


def sum_prompt_chars(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += len(part.get("text", ""))
                    elif part.get("type") in ("image_url", "file_url"):
                        total += 32  # approximate cost of an attachment
    return total


def _price(model: ModelConfig, chars: int, seconds: float) -> int:
    request = model.price_per_request_cents
    char_cost = int(round(model.price_per_1k_chars_cents * chars / 1000))
    time_cost = int(round(model.price_per_minute_cents * seconds / 60))
    return request + char_cost + time_cost


def precharge_cents(model: ModelConfig, prompt_chars: int) -> int:
    capped = min(
        prompt_chars * PRECHARGE_CHARS_FACTOR + PRECHARGE_CHARS_FLOOR, MAX_CHARS_CAP
    )
    return _price(model, capped, model.timeout_seconds)


def compute_usage(model: ModelConfig, prompt_chars: int, completion_chars: int, duration_seconds: float) -> dict:
    capped_chars = min(completion_chars, min(prompt_chars * PRECHARGE_CHARS_FACTOR + PRECHARGE_CHARS_FLOOR, MAX_CHARS_CAP))
    duration = min(duration_seconds, model.timeout_seconds)
    actual = _price(model, capped_chars, duration)
    prompt_tokens = math.ceil(prompt_chars / 4)
    completion_tokens = math.ceil(capped_chars / 4)
    return {
        "prompt_chars": prompt_chars,
        "completion_chars": capped_chars,
        "completion_chars_raw": completion_chars,
        "duration_seconds": int(duration),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "request_cents": model.price_per_request_cents,
        "char_cents": int(round(model.price_per_1k_chars_cents * capped_chars / 1000)),
        "time_cents": int(round(model.price_per_minute_cents * duration / 60)),
        "total_cents": actual,
    }


async def hold_precharge(db: AsyncSession, task: Task, user: User, model: ModelConfig, amount_cents: int) -> None:
    if user.balance_cents < amount_cents:
        raise OpenAIError(
            f"Insufficient balance. This request requires a hold of "
            f"{amount_cents/100:.2f} (your balance is {user.balance_cents/100:.2f}). "
            f"Please top up your account.",
            status_code=402,
            error_type="insufficient_quota",
            code="insufficient_balance",
        )
    user.balance_cents -= amount_cents
    db.add(
        Transaction(
            task_id=task.id,
            kind=TransactionKind.preauth_hold,
            user_id=user.id,
            amount_cents=amount_cents,
            note=f"hold for task {task.id}",
        )
    )
    await db.commit()


async def settle(
    db: AsyncSession,
    task: Task,
    model: ModelConfig,
    worker: Worker | None,
    precharge_cents: int,
    commission_rate: float,
) -> dict:
    """Charge the actual cost, refund the unused hold, credit worker + platform."""
    duration = 0.0
    if task.assigned_at and task.completed_at:
        duration = (task.completed_at - task.assigned_at).total_seconds()
    usage = compute_usage(
        model,
        sum_prompt_chars(task.messages),
        len(task.reply_text or ""),
        max(0.0, duration),
    )
    actual = usage["total_cents"]
    refund = max(0, precharge_cents - actual)

    user = await db.get(User, task.user_id) if task.user_id else None
    if user is not None:
        user.balance_cents += refund
        db.add(
            Transaction(
                task_id=task.id,
                kind=TransactionKind.refund,
                user_id=user.id,
                amount_cents=refund,
                note=f"release hold for task {task.id}",
            )
        )
    earning = int(round(actual * (1 - commission_rate)))
    commission = actual - earning
    if worker is not None:
        worker.earnings_cents += earning
        db.add(
            Transaction(
                task_id=task.id,
                kind=TransactionKind.worker_earning,
                worker_id=worker.id,
                amount_cents=earning,
                note=f"earning for task {task.id}",
            )
        )
    db.add(
        Transaction(
            task_id=task.id,
            kind=TransactionKind.platform_commission,
            amount_cents=commission,
            note=f"platform fee for task {task.id}",
        )
    )
    task.usage = usage
    await db.commit()
    return usage

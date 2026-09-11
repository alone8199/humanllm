"""Backward-compatible entry point for task dispatching.

The implementation lives in ``app.services.dispatch``. Keeping these exports
here avoids forcing the existing routers and worker code to change imports all
at once.
"""
from app.services.dispatch import (
    active_task_count,
    assign_to_worker,
    auto_assign,
    candidate_worker_ids,
    enqueue_for_grab,
    requeue_task,
    task_payload_for_public,
)

__all__ = [
    "active_task_count",
    "assign_to_worker",
    "auto_assign",
    "candidate_worker_ids",
    "enqueue_for_grab",
    "requeue_task",
    "task_payload_for_public",
]

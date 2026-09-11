"""Public compatibility module for HumanLLM's SQLAlchemy models.

Model declarations live in ``model_entities.py`` while enums and permission
helpers live in ``model_types.py``. Existing imports from ``app.models`` remain
valid, so this refactor does not require a repository-wide import migration.
"""
from app.model_types import (
    ALL_PERMISSIONS,
    TaskStatus,
    TransactionKind,
    UserRole,
    WorkerStatus,
    user_has_perm,
)
from app.model_entities import (
    ApiKey,
    Attachment,
    EventLog,
    ModelConfig,
    Task,
    Transaction,
    UploadedFile,
    User,
    Worker,
    WorkerModel,
    gen_uuid,
    utcnow,
)

__all__ = [
    "ALL_PERMISSIONS",
    "ApiKey",
    "Attachment",
    "EventLog",
    "ModelConfig",
    "Task",
    "TaskStatus",
    "Transaction",
    "TransactionKind",
    "UploadedFile",
    "User",
    "UserRole",
    "Worker",
    "WorkerModel",
    "WorkerStatus",
    "gen_uuid",
    "user_has_perm",
    "utcnow",
]

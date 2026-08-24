"""SQLAlchemy ORM models for HumanLLM."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


def gen_uuid() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    # HumanLLM ships with a two-tier account model:
    #   - super_admin: full control (users, models, keys, everything).
    #   - staff: permissions are granted per-module via User.permissions.
    super_admin = "super_admin"
    staff = "staff"


# Granular permission bits (module-level access). "users" management is
# exclusive to super_admin and is not part of this list.
ALL_PERMISSIONS = [
    "overview",   # stats / dashboard landing
    "workbench",  # human reply workbench (WebSocket worker)
    "models",     # model CRUD
    "apikeys",    # API key management
    "tasks",      # task list / detail
    "usage",      # usage records
    "logs",       # event logs
]


def user_has_perm(user: "User", perm: str) -> bool:
    """super_admin always passes; staff must have the permission in their array."""
    if user.role == UserRole.super_admin:
        return True
    if user.role == UserRole.staff:
        perms = user.permissions or []
        return perm in perms
    return False


class WorkerStatus(str, enum.Enum):
    offline = "offline"
    online = "online"
    busy = "busy"


class TaskStatus(str, enum.Enum):
    pending = "pending"      # waiting for a worker to grab / be assigned
    assigned = "assigned"    # assigned to a worker, not yet streaming
    streaming = "streaming"  # worker is sending chunks
    waiting_tool = "waiting_tool"  # worker returned tool_calls; awaiting tool results from caller
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


class TransactionKind(str, enum.Enum):
    charge = "charge"                    # user debited for a request
    preauth_hold = "preauth_hold"        # funds reserved at creation
    refund = "refund"                    # hold released back
    worker_earning = "worker_earning"    # worker credited
    platform_commission = "platform_commission"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole, native_enum=False), nullable=False, default=UserRole.staff)
    # Permission bits for staff accounts (list of ALL_PERMISSIONS strings).
    # super_admin ignores this (always full access); None behaves as [] for staff.
    permissions = Column(JSON, nullable=True)
    balance_cents = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    # Bumped on every password change so previously issued JWTs are rejected
    # (force-logout / token revocation without a shared blacklist).
    token_version = Column(Integer, nullable=False, default=0)
    is_initial_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (UniqueConstraint("key_hash", name="uq_api_key_hash"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_prefix = Column(String(32), nullable=False, index=True)
    key_hash = Column(String(64), nullable=False)
    # Full key stored so the admin can always view/copy it later. This is a
    # single-admin system; keep it plaintext for simplicity (it is also
    # returned by the admin list endpoint).
    full_key = Column(String(128), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="default")
    is_active = Column(Boolean, nullable=False, default=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    user = relationship("User", back_populates="api_keys")


class Worker(Base):
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False, default="")
    hashed_password = Column(String(255), nullable=False)
    # When set, this worker belongs to an admin user (the admin IS the worker).
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(Enum(WorkerStatus, native_enum=False), nullable=False, default=WorkerStatus.offline)
    current_task_id = Column(String(36), nullable=True, index=True)
    skills = Column(JSON, nullable=False, default=list)
    earnings_cents = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    models = relationship(
        "ModelConfig",
        secondary="worker_models",
        back_populates="workers",
        viewonly=True,
    )


class ModelConfig(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    # Pricing is in cents (1/100 of a currency unit) to avoid float errors.
    price_per_request_cents = Column(Integer, nullable=False, default=0)
    price_per_1k_chars_cents = Column(Integer, nullable=False, default=0)
    price_per_minute_cents = Column(Integer, nullable=False, default=0)
    concurrency = Column(Integer, nullable=False, default=1)
    timeout_seconds = Column(Integer, nullable=False, default=600)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    workers = relationship(
        "Worker",
        secondary="worker_models",
        back_populates="models",
        viewonly=True,
    )


class WorkerModel(Base):
    __tablename__ = "worker_models"
    __table_args__ = (UniqueConstraint("worker_id", "model_name", name="uq_worker_model"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    worker_id = Column(Integer, ForeignKey("workers.id", ondelete="CASCADE"), nullable=False)
    model_name = Column(String(64), ForeignKey("models.name", ondelete="CASCADE"), nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    model = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True)
    # Full normalized message list (with extracted text/images/files).
    messages = Column(JSON, nullable=False, default=list)
    # Tool/function definitions from the request (for human-in-the-loop
    # function calling). The human worker fills the call + result.
    tools = Column(JSON, nullable=True)
    # Human-filled tool calls (function calling). Each: {id,name,arguments}.
    tool_calls = Column(JSON, nullable=True)
    # Stable conversation id for multi-round tool calling: follow-up requests
    # that carry tool results continue the same task instead of creating a new one.
    session_id = Column(String(64), nullable=True, index=True)
    status = Column(Enum(TaskStatus, native_enum=False), nullable=False, default=TaskStatus.pending, index=True)
    assigned_worker_id = Column(Integer, ForeignKey("workers.id", ondelete="SET NULL"), nullable=True, index=True)
    stream = Column(Boolean, nullable=False, default=False)
    precharge_cents = Column(Integer, nullable=False, default=0)
    reply_text = Column(Text, nullable=False, default="")
    usage = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    finish_reason = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    timeout_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="tasks")
    attachments = relationship("Attachment", back_populates="task", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # image | file
    source = Column(String(16), nullable=False, default="url")  # url | upload | data
    filename = Column(String(255), nullable=False, default="")
    content_type = Column(String(128), nullable=True)
    storage_key = Column(String(512), nullable=True)  # for uploaded/data files
    url = Column(Text, nullable=True)  # external or served URL
    size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    task = relationship("Task", back_populates="attachments")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(Enum(TransactionKind, native_enum=False), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    worker_id = Column(Integer, ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)
    amount_cents = Column(Integer, nullable=False)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    storage_key = Column(String(512), nullable=False)
    filename = Column(String(255), nullable=False, default="")
    content_type = Column(String(128), nullable=True)
    size = Column(Integer, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class EventLog(Base):
    __tablename__ = "event_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=True, index=True)
    actor = Column(String(32), nullable=True)  # system | worker:<id> | user:<id>
    kind = Column(String(32), nullable=False)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

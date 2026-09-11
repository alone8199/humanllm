"""SQLAlchemy entity definitions for HumanLLM."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base
from app.model_types import TaskStatus, TransactionKind, UserRole, WorkerStatus


def utcnow() -> datetime:
    return datetime.utcnow()


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole, native_enum=False), nullable=False, default=UserRole.staff)
    permissions = Column(JSON, nullable=True)
    balance_cents = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
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
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    status = Column(Enum(WorkerStatus, native_enum=False), nullable=False, default=WorkerStatus.offline)
    current_task_id = Column(String(36), nullable=True, index=True)
    skills = Column(JSON, nullable=False, default=list)
    earnings_cents = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    models = relationship("ModelConfig", secondary="worker_models", back_populates="workers", viewonly=True)


class ModelConfig(Base):
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(128), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    price_per_request_cents = Column(Integer, nullable=False, default=0)
    price_per_1k_chars_cents = Column(Integer, nullable=False, default=0)
    price_per_minute_cents = Column(Integer, nullable=False, default=0)
    concurrency = Column(Integer, nullable=False, default=1)
    timeout_seconds = Column(Integer, nullable=False, default=600)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    workers = relationship("Worker", secondary="worker_models", back_populates="models", viewonly=True)


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
    messages = Column(JSON, nullable=False, default=list)
    tools = Column(JSON, nullable=True)
    tool_calls = Column(JSON, nullable=True)
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
    kind = Column(String(16), nullable=False)
    source = Column(String(16), nullable=False, default="url")
    filename = Column(String(255), nullable=False, default="")
    content_type = Column(String(128), nullable=True)
    storage_key = Column(String(512), nullable=True)
    url = Column(Text, nullable=True)
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
    actor = Column(String(32), nullable=True)
    kind = Column(String(32), nullable=False)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

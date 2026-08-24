"""Pydantic schemas for requests/responses (OpenAI-compatible where relevant)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


# --------------------------- Chat completions ---------------------------
class ImageURL(BaseModel):
    url: str
    detail: Optional[str] = None


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageURLPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


class FileURLPart(BaseModel):
    # Custom extension: reference an uploaded file / arbitrary document by URL.
    type: Literal["file_url"] = "file_url"
    file_url: ImageURL


ChatContentPart = Union[TextPart, ImageURLPart, FileURLPart]


class ChatMessage(BaseModel):
    role: str
    # content may be None for assistant messages carrying tool_calls (standard
    # OpenAI multi-round tool-calling format).
    content: Optional[Union[str, list[dict[str, Any]]]] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None


class StreamOptions(BaseModel):
    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    n: Optional[int] = None
    stop: Optional[Union[str, list[str]]] = None
    user: Optional[str] = None
    stream_options: Optional[StreamOptions] = None
    response_format: Optional[dict[str, Any]] = None
    # Function calling (human-filled, zero AI): the caller sends tool
    # definitions; the human worker decides the call and fills the result.
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[Union[str, dict[str, Any]]] = None

    model_config = {"extra": "allow"}


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "humanllm"
    display_name: Optional[str] = None
    description: Optional[str] = None
    pricing: Optional[dict[str, Any]] = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Extra human-relevant fields (not standard OpenAI, but useful).
    prompt_chars: int = 0
    completion_chars: int = 0
    duration_seconds: int = 0


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: dict[str, Any]
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage


class ChatCompletionChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionChunkChoice]
    usage: Optional[Usage] = None


# ------------------------------- Files -------------------------------
class FileObject(BaseModel):
    id: str
    object: str = "file"
    filename: str
    content_type: Optional[str] = None
    size: int
    url: str
    created_at: int


# ---------------------------- Auth -----------------------------
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    worker_id: Optional[int] = None
    username: Optional[str] = None
    permissions: Optional[list[str]] = None  # None => super_admin (full access)


class UserPublic(BaseModel):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    permissions: Optional[list[str]] = None
    is_active: bool
    balance_cents: int = 0
    created_at: datetime
    worker_status: Optional[str] = None
    worker_id: Optional[int] = None


class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    role: str = "staff"
    permissions: list[str] = []


class UserUpdate(BaseModel):
    role: Optional[str] = None
    permissions: Optional[list[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    email: Optional[str] = None


class WorkerPublic(BaseModel):
    id: int
    username: str
    display_name: str
    status: str
    skills: list[str] = []
    earnings_cents: int = 0
    current_task_id: Optional[str] = None
    served_models: list[str] = []
    # The dashboard account this worker belongs to (1 user == 1 worker).
    owner_username: Optional[str] = None
    owner_id: Optional[int] = None


# ---------------------------- Admin schemas ----------------------------
class ApiKeyCreate(BaseModel):
    name: str = "default"


class ApiKeyPublic(BaseModel):
    id: int
    name: str
    key_prefix: str
    full_key: Optional[str] = None  # persisted so the admin can always see it
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    key: str  # full key, persisted and always viewable
    key_prefix: str


class ModelCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    description: Optional[str] = ""
    price_per_request_cents: int = 0
    price_per_1k_chars_cents: int = 0
    price_per_minute_cents: int = 0
    concurrency: int = 1
    timeout_seconds: int = 600
    is_active: bool = True
    worker_usernames: list[str] = []


class ModelPublic(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    price_per_request_cents: int
    price_per_1k_chars_cents: int
    price_per_minute_cents: int
    concurrency: int
    timeout_seconds: int
    is_active: bool
    created_at: datetime
    worker_usernames: list[str] = []


class TaskPublic(BaseModel):
    id: str
    model: str
    user_id: Optional[int]
    api_key_id: Optional[int]
    status: str
    stream: bool
    reply_text: str
    usage: Optional[dict[str, Any]]
    error: Optional[str]
    finish_reason: Optional[str]
    created_at: datetime
    assigned_at: Optional[datetime]
    completed_at: Optional[datetime]
    assigned_worker_id: Optional[int]


class StatsResponse(BaseModel):
    users: int
    workers: int
    workers_online: int
    models: int
    tasks_total: int
    tasks_completed: int
    tasks_pending: int
    revenue_cents: int
    worker_payouts_cents: int
    platform_commission_cents: int

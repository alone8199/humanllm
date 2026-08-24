"""Application configuration loaded from environment variables.

All settings can be overridden via environment variables or a .env file.
A sensible local-default profile is provided so the project runs with zero
external dependencies (SQLite + local file storage + in-memory queue).
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from dotenv import load_dotenv

    # Load .env from the backend directory so APP_BASE_URL / EXEC_URL /
    # JWT_SECRET / AUTO_ASSIGN etc. are honored (systemd does not inject them).
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Optional[str], default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


class Settings:
    # --- Core ---
    PROJECT_NAME: str = "HumanLLM"
    VERSION: str = "1.0.0"
    DEBUG: bool = _bool(os.getenv("DEBUG"), False)

    # --- Database ---
    # Async SQLAlchemy URL. SQLite for zero-dep dev/test, Postgres for prod.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./humanllm.db"
    )
    AUTO_MIGRATE: bool = _bool(os.getenv("AUTO_MIGRATE"), True)

    # --- Redis / Queue ---
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")  # None => in-memory queue
    QUEUE_BACKEND: str = os.getenv("QUEUE_BACKEND", "auto")  # auto|redis|memory

    # --- Storage ---
    # local => filesystem under STORAGE_LOCAL_PATH
    # s3    => MinIO / S3 compatible (STORAGE_* vars)
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local")
    STORAGE_LOCAL_PATH: str = os.getenv("STORAGE_LOCAL_PATH", "./storage")
    STORAGE_PUBLIC_BASE: str = os.getenv(
        "STORAGE_PUBLIC_BASE", ""
    )  # e.g. http://localhost:9000/humanllm
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "humanllm")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "humanllm-secret")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "humanllm")
    MINIO_USE_SSL: bool = _bool(os.getenv("MINIO_USE_SSL"), False)

    # --- Security ---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me-in-prod")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_SECONDS: int = _int(os.getenv("JWT_EXPIRE_SECONDS"), 60 * 60 * 24 * 7)
    API_KEY_HEADER: str = "Authorization"
    # If the JWT secret is left at the dev placeholder AND we are not in DEBUG
    # mode, generate an ephemeral random secret at startup (logged loudly) so
    # tokens are never forgeable-by-default. Set to False to hard-fail instead.
    JWT_REQUIRE_SECRET: bool = _bool(os.getenv("JWT_REQUIRE_SECRET"), False)

    # ---- Rate limiting / brute-force protection (anti-cracking) ----
    RATE_LIMIT_ENABLED: bool = _bool(os.getenv("RATE_LIMIT_ENABLED"), True)
    # Per-IP ceiling across ALL routes (DoS guard). Generous by default.
    RATE_GLOBAL_PER_MIN: int = _int(os.getenv("RATE_GLOBAL_PER_MIN"), 600)
    # Login attempts per IP per minute.
    RATE_LOGIN_PER_MIN: int = _int(os.getenv("RATE_LOGIN_PER_MIN"), 10)
    # Chat completions per API key per minute.
    RATE_APIKEY_CHAT_PER_MIN: int = _int(os.getenv("RATE_APIKEY_CHAT_PER_MIN"), 60)
    # Lock the account+IP after this many cumulative login failures.
    LOGIN_MAX_FAIL: int = _int(os.getenv("LOGIN_MAX_FAIL"), 5)
    LOGIN_LOCKOUT_SECONDS: int = _int(os.getenv("LOGIN_LOCKOUT_SECONDS"), 900)

    # ---- Password policy ----
    PASSWORD_MIN_LENGTH: int = _int(os.getenv("PASSWORD_MIN_LENGTH"), 12)
    PASSWORD_REQUIRE_UPPER: bool = _bool(os.getenv("PASSWORD_REQUIRE_UPPER"), True)
    PASSWORD_REQUIRE_LOWER: bool = _bool(os.getenv("PASSWORD_REQUIRE_LOWER"), True)
    PASSWORD_REQUIRE_DIGIT: bool = _bool(os.getenv("PASSWORD_REQUIRE_DIGIT"), True)
    PASSWORD_REQUIRE_SPECIAL: bool = _bool(os.getenv("PASSWORD_REQUIRE_SPECIAL"), False)

    # ---- Request hardening ----
    # Reject request bodies larger than this (bytes). Guards inline base64
    # attachments / message floods.
    MAX_BODY_BYTES: int = _int(os.getenv("MAX_BODY_BYTES"), 25 * 1024 * 1024)
    # Cap a single inline (data:) attachment after base64 decode (bytes).
    MAX_INLINE_BYTES: int = _int(os.getenv("MAX_INLINE_BYTES"), 10 * 1024 * 1024)
    # Defensive HTTP response headers + Server banner strip.
    SECURITY_HEADERS_ENABLED: bool = _bool(os.getenv("SECURITY_HEADERS_ENABLED"), True)
    # Send HSTS (only enable when the site is served over HTTPS).
    FORCE_HSTS: bool = _bool(os.getenv("FORCE_HSTS"), False)
    # When CORS origins include "*", drop credentials (wildcard+credentials is
    # both browser-invalid and a CSRF/leak risk).
    STRICT_CORS: bool = _bool(os.getenv("STRICT_CORS"), True)

    # --- Dispatch / Billing ---
    AUTO_ASSIGN: bool = _bool(os.getenv("AUTO_ASSIGN"), True)
    TASK_TIMEOUT_SECONDS: int = _int(os.getenv("TASK_TIMEOUT_SECONDS"), 600)
    COMMISSION_RATE: float = float(os.getenv("COMMISSION_RATE", "0.2"))
    COMMISSION_RATE_REAL: float = COMMISSION_RATE  # alias used by settlement

    # --- Off-hours (营业时间) ---
    # Between OFF_HOURS_END (e.g. 08:00) and OFF_HOURS_START (e.g. 20:00) the
    # API accepts requests; outside that window it refuses with "不接单了".
    # Times are in the server's local timezone (CST, UTC+8 on this host).
    OFF_HOURS_ENABLED: bool = _bool(os.getenv("OFF_HOURS_ENABLED"), False)
    OFF_HOURS_START: int = _int(os.getenv("OFF_HOURS_START"), 20)  # 20:00 = 不接单开始
    OFF_HOURS_END: int = _int(os.getenv("OFF_HOURS_END"), 8)       # 08:00 = 不接单结束
    OFF_HOURS_MESSAGE: str = os.getenv("OFF_HOURS_MESSAGE", "不接单了")
    # Pre-charge the user this fraction of the estimated max cost (hold).
    PRECHARGE_RATE: float = float(os.getenv("PRECHARGE_RATE", "1.0"))

    # --- Seed (first boot) ---
    # A single administrator account. The admin also serves as the only human
    # worker (接单员), so there is no separate worker/consumer password.
    DEFAULT_PASSWORD: str = os.getenv("DEFAULT_PASSWORD", "admin123")
    DEFAULT_ADMIN_USERNAME: str = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("DEFAULT_ADMIN_PASSWORD", DEFAULT_PASSWORD)
    DEFAULT_ADMIN_EMAIL: str = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@humanllm.dev")

    # --- Misc ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = _int(os.getenv("PORT"), 8000)
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ORIGINS",
            "*,"  # default to wildcard in dev/single-origin deployments
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8000,http://127.0.0.1:8000,"
            "http://localhost:8200,http://127.0.0.1:8200,"
            "https://humanllm-frontend.vercel.app,"
            "https://humanllm-frontend-git-main-simimasai111s-projects.vercel.app",
        ).split(",")
        if o.strip()
    ]
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")

    @property
    def resolved_queue_backend(self) -> str:
        if self.QUEUE_BACKEND == "auto":
            return "redis" if self.REDIS_URL else "memory"
        return self.QUEUE_BACKEND

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings()

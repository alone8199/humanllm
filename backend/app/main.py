"""HumanLLM FastAPI application entrypoint."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send
import asyncio

from app.broker import broker
from app.config import settings
from app.database import AsyncSessionLocal
from app.middleware import (
    BodySizeLimitMiddleware,
    GlobalRateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.migrate import run_migrations
from app.openai_errors import OpenAIError, openai_error_response, openai_validation_handler
from app.routers import admin, chat, files, health, models, worker, worker_auth
from app.seed import seed_initial

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("humanllm")


def _bootstrap_secret() -> None:
    """Never ship forgeable-by-default JWTs.

    If JWT_SECRET is still the dev placeholder:
      - DEBUG=True  -> keep the dev secret (local convenience).
      - DEBUG=False -> generate an ephemeral random secret for this process and
        warn loudly. Tokens will not survive a restart; operators MUST set a
        real JWT_SECRET. With JWT_REQUIRE_SECRET=True we hard-fail instead.
    """
    if settings.JWT_SECRET != "dev-secret-change-me-in-prod":
        return
    if settings.DEBUG:
        logger.warning("JWT_SECRET is the dev placeholder but DEBUG=True — OK for local dev.")
        return
    import secrets as _secrets

    if settings.JWT_REQUIRE_SECRET:
        raise RuntimeError(
            "JWT_SECRET is still the dev placeholder in production. "
            "Set a long random JWT_SECRET environment variable before starting."
        )
    settings.JWT_SECRET = _secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET was unset — generated an EPHEMERAL secret for this process. "
        "Set JWT_SECRET in the environment or all issued tokens expire on restart."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap_secret()
    logger.info("HumanLLM starting up (queue backend=%s, storage=%s)...",
                settings.resolved_queue_backend, settings.STORAGE_BACKEND)
    await run_migrations()
    await broker.startup()
    async with AsyncSessionLocal() as db:
        seeded = await seed_initial(db)
        logger.info("Seed result: %s", seeded)
    yield
    await broker.shutdown()


app = FastAPI(
    title="HumanLLM",
    version=settings.VERSION,
    description="Human is the Model. OpenAI-compatible API served by real humans.",
    lifespan=lifespan,
)

# CORS: allow all origins by default so the same-origin SPA (or any split
# frontend) can talk to the backend without friction. Tighten via CORS_ORIGINS
# in production if needed. A wildcard origin combined with credentials is both
# browser-invalid and unsafe, so we drop credentials when "*" is present.
_cors_origins = settings.CORS_ORIGINS or ["*"]
_cors_credentials = True
if "*" in _cors_origins and settings.STRICT_CORS:
    _cors_credentials = False
    logger.warning("CORS wildcard '*' detected with STRICT_CORS=True — credentials disabled.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheMiddleware:
    """对 /api/ 下的 JSON 响应禁用浏览器缓存，确保列表页每次打开都拉取最新数据。
    静态资源（/assets、SPA 入口）不加，避免影响前端加载性能。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", b"no-store, no-cache, must-revalidate"))
                headers.append((b"pragma", b"no-cache"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(NoCacheMiddleware)

# Security hardening middleware (order: outermost added last).
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Exception handlers -> OpenAI-compatible error envelope.
app.add_exception_handler(OpenAIError, lambda req, exc: openai_error_response(exc))
app.add_exception_handler(RequestValidationError, openai_validation_handler)
app.add_exception_handler(Exception, lambda req, exc: _unhandled(req, exc))


def _unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Internal server error.", "type": "api_error", "code": "api_error"}},
    )


app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(files.router)
# Internal/admin/worker REST APIs live under /api/*; the WebSocket stays at /ws.
app.include_router(worker_auth.router, prefix="/api")
app.include_router(worker.router, prefix="/api")
app.include_router(worker.ws_router)
app.include_router(admin.router, prefix="/api")

# ----------------------- Frontend (same-origin, no separation) -----------------------
# The built SPA is served from the same origin/port as the API + WebSocket,
# so the frontend's IP/domain IS the API endpoint. API routes take precedence;
# everything else falls back to index.html (SPA client-side routing).
# Project root is two levels up from this file (backend/app -> backend -> root).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_FRONTEND_DIST = os.path.join(_PROJECT_ROOT, "frontend", "dist")


def _mount_frontend() -> None:
    if not os.path.isdir(_FRONTEND_DIST):
        logger.warning(
            "Frontend dist not found at %s — serving API only. "
            "Run `npm run build` in frontend/ to enable the web UI.",
            _FRONTEND_DIST,
        )
        return

    # Static assets (hashed files) served under /assets.
    assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Root-level static files (favicon, robots.txt, etc.) returned directly
    # instead of falling through to the SPA catch-all.
    @app.get("/favicon.svg")
    async def favicon():
        p = os.path.join(_FRONTEND_DIST, "favicon.svg")
        if os.path.isfile(p):
            return FileResponse(p, media_type="image/svg+xml")
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/{full_path:path}")
    async def spa_index(full_path: str):
        # API/WS/auth/admin paths are already handled by routers above; this is
        # the catch-all for client-side routes and index.html.
        index = os.path.join(_FRONTEND_DIST, "index.html")
        return FileResponse(index)


if not os.getenv("DISABLE_FRONTEND_MOUNT"):
    _mount_frontend()

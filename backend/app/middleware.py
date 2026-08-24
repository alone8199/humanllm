"""Security hardening middleware.

Three layers, all opt-out via config:

1. SecurityHeadersMiddleware — sets defensive HTTP response headers
   (clickjacking / MIME-sniff / referrer / CSP / HSTS) and strips ``Server``.
2. BodySizeLimitMiddleware — rejects oversized request bodies (DoS guard).
3. GlobalRateLimitMiddleware — per-IP ceiling across *all* routes so a single
   attacker IP cannot exhaust the worker pool or DB with request floods.
"""
from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.ratelimit import limiter

logger = logging.getLogger("humanllm.security")


# A lenient-but-safe CSP: same-origin scripts/styles, allows inline styles
# (most SPAs), blocks framing (clickjacking), and permits data: images plus
# https: image/connect for the chat UI. Tighten per your frontend's needs.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self' https: wss: ws:; "
    "font-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        if settings.SECURITY_HEADERS_ENABLED:
            response.headers.setdefault("Content-Security-Policy", _CSP)
        # Strip the framework/version banner.
        for _h in ("server", "x-powered-by"):
            if _h in response.headers:
                del response.headers[_h]
        # HSTS only when the deployment is actually behind HTTPS.
        if settings.FORCE_HSTS:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            raw = request.headers.get("content-length")
            if raw:
                try:
                    length = int(raw)
                except ValueError:
                    length = 0
                if length > settings.MAX_BODY_BYTES:
                    logger.warning(
                        "Rejected oversized body from %s: %d bytes (limit %d)",
                        request.client.host if request.client else "unknown",
                        length,
                        settings.MAX_BODY_BYTES,
                    )
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": {
                                "message": "Request payload too large.",
                                "type": "invalid_request_error",
                                "code": "payload_too_large",
                            }
                        },
                    )
        return await call_next(request)


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Health checks and static assets are exempt so monitoring/SPAs never
        # trip the global ceiling.
        path = request.url.path
        if path.startswith(("/health", "/assets", "/favicon")):
            return await call_next(request)
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        allowed, _remaining, retry_after = limiter.check(
            f"global:ip:{ip}", settings.RATE_GLOBAL_PER_MIN, 60
        )
        if not allowed:
            logger.warning("Global rate limit hit for %s on %s", ip, path)
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "message": "Too many requests. Slow down and retry later.",
                        "type": "rate_limit_error",
                        "code": "rate_limited",
                    }
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )
        return await call_next(request)

"""OpenAI-compatible error formatting.

All errors returned by the OpenAI-compatible surface use this shape:
{
  "error": {
    "message": "...",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_request_error"
  }
}
"""
from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

OPENAI_ERROR_TYPES = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "try_again",
    422: "invalid_request_error",
    429: "rate_limit_error",
    500: "api_error",
}


class OpenAIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        error_type: str | None = None,
        param: str | None = None,
        code: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.error_type = error_type or OPENAI_ERROR_TYPES.get(status_code, "api_error")
        self.param = param
        self.code = code or self.error_type
        super().__init__(message)


def openai_error_response(exc: OpenAIError) -> JSONResponse:
    body = {
        "error": {
            "message": exc.message,
            "type": exc.error_type,
            "param": exc.param,
            "code": exc.code,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=body)


async def openai_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Flatten pydantic v2 errors into a readable message.
    msgs = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msgs.append(f"{loc}: {err.get('msg')}" if loc else err.get("msg"))
    body = {
        "error": {
            "message": "; ".join(msgs) or "Invalid request.",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_request_error",
        }
    }
    return JSONResponse(status_code=422, content=body)

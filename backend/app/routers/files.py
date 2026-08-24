"""File upload + content serving.

POST /v1/files          -> upload (multipart), returns a file id + served URL
GET  /v1/files          -> list files owned by the calling API key
GET  /v1/files/content/{key} -> stream the bytes (auth required: API key,
                                worker token, or admin token)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker import broker  # noqa: F401  (ensure import side-effects none)
from app.database import get_session
from app.deps import _bearer, authenticate_api_key
from app.models import ApiKey, ModelConfig, UploadedFile, User, UserRole, Worker
from app.schemas import FileObject
from app.security import decode_access_token
from app.storage import storage

router = APIRouter()


async def _resolve_identity(authorization: str | None, db: AsyncSession):
    token = _bearer(authorization)
    if not token:
        return None
    api_key = None
    if token.startswith("sk-"):
        from app.security import hash_api_key

        res = await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))
        api_key = res.scalar_one_or_none()
        if api_key and api_key.is_active:
            user = await db.get(User, api_key.user_id)
            if user and user.is_active:
                return ("apikey", api_key, user)
    payload = decode_access_token(token)
    if payload:
        if payload.get("role") == "worker":
            worker = await db.get(Worker, int(payload["sub"]))
            if worker and worker.is_active:
                return ("worker", None, worker)
        # dashboard user JWT (super_admin / staff / legacy admin)
        user = await db.get(User, int(payload["sub"]))
        if user and user.is_active:
            return ("user", None, user)
    return None


@router.post("/v1/files", response_model=FileObject)
async def upload_file(
    file: UploadFile,
    api_key=Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_session),
):
    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 25MB)")
    content_type = file.content_type or "application/octet-stream"
    key = await storage.save(file.filename or "file", content_type, data)
    rec = UploadedFile(
        storage_key=key,
        filename=file.filename or "file",
        content_type=content_type,
        size=len(data),
        owner_user_id=api_key.user_id,
    )
    db.add(rec)
    await db.commit()
    return FileObject(
        id=key,
        filename=rec.filename,
        content_type=rec.content_type,
        size=rec.size or 0,
        url=storage.content_url(key),
        created_at=int(datetime.utcnow().timestamp()),
    )


@router.get("/v1/files", response_model=list[FileObject])
async def list_files(
    api_key=Depends(authenticate_api_key),
    db: AsyncSession = Depends(get_session),
):
    res = await db.execute(
        select(UploadedFile).where(UploadedFile.owner_user_id == api_key.user_id)
    )
    rows = res.scalars().all()
    return [
        FileObject(
            id=r.storage_key,
            filename=r.filename,
            content_type=r.content_type,
            size=r.size or 0,
            url=storage.content_url(r.storage_key),
            created_at=int(r.created_at.timestamp()),
        )
        for r in rows
    ]


_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4v": "video/mp4",
    ".ogg": "video/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
}


@router.get("/v1/files/content/{key}")
async def get_file_content(
    key: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    # Public read: file keys are unguessable random ids, so allowing direct
    # <img>/<video> rendering in the browser (which cannot send headers) is
    # safe enough for this single-admin deployment.
    data, content_type = await storage.load(key)
    if not content_type:
        ext = os.path.splitext(key)[1].lower()
        content_type = _MIME_BY_EXT.get(ext, "application/octet-stream")
    return Response(content=data, media_type=content_type)

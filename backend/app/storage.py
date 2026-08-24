"""File storage abstraction.

Backends:
  - local: writes to STORAGE_LOCAL_PATH on disk, served via /v1/files/content/{key}
  - s3:    MinIO / S3-compatible object storage via aioboto3

For both backends, stored files are exposed to clients through the
/v1/files/content/{key} endpoint (auth required), so the workbench can
preview them regardless of where bytes physically live.
"""
from __future__ import annotations
import asyncio

import os
import secrets
from typing import Optional

import aioboto3
from app.config import settings


def _extension(content_type: str, filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext:
        return ext.lstrip(".")
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/webp": "webp",
        "application/pdf": "pdf",
        "text/plain": "txt",
        "text/csv": "csv",
        "application/json": "json",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    }
    return mapping.get(content_type, "bin")


class StorageService:
    def __init__(self) -> None:
        self.backend = settings.STORAGE_BACKEND
        self.local_path = settings.STORAGE_LOCAL_PATH
        if self.backend == "local":
            os.makedirs(self.local_path, exist_ok=True)
        self._session = aioboto3.Session()

    def _new_key(self, filename: str, content_type: str) -> str:
        return f"{secrets.token_hex(16)}.{_extension(content_type, filename)}"

    def content_url(self, key: str) -> str:
        base = settings.APP_BASE_URL.rstrip("/")
        return f"{base}/v1/files/content/{key}"

    async def save(self, filename: str, content_type: str, data: bytes) -> str:
        key = self._new_key(filename, content_type)
        if self.backend == "local":
            path = os.path.join(self.local_path, key)
            await asyncio.to_thread(self._write_local, path, data)
        else:
            await self._s3_put(key, data, content_type)
        return key

    @staticmethod
    def _write_local(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)

    async def load(self, key: str) -> tuple[bytes, Optional[str]]:
        if self.backend == "local":
            path = os.path.join(self.local_path, os.path.basename(key))
            with open(path, "rb") as f:
                data = f.read()
            return data, None
        return await self._s3_get(key)

    async def _s3_put(self, key: str, data: bytes, content_type: str) -> None:
        async with self._session.client(
            "s3",
            endpoint_url=f"http{'s' if settings.MINIO_USE_SSL else ''}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        ) as client:
            await client.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=key,
                Body=data,
                ContentType=content_type,
            )

    async def _s3_get(self, key: str) -> tuple[bytes, Optional[str]]:
        async with self._session.client(
            "s3",
            endpoint_url=f"http{'s' if settings.MINIO_USE_SSL else ''}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
        ) as client:
            resp = await client.get_object(Bucket=settings.MINIO_BUCKET, Key=key)
            async with resp["Body"] as stream:
                data = await stream.read()
            return data, resp.get("ContentType")


storage = StorageService()

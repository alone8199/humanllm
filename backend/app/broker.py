"""Live runtime broker.

Responsibilities (in-process, required for WebSocket + SSE delivery):
  * registry of connected worker WebSocket outgoing queues
  * per-task event channels consumed by the SSE / non-stream callers
  * in-memory pending queue for grab-mode tasks

Optional Redis backend (when REDIS_URL is set): the pending queue is also
mirrored into Redis lists and new-task notifications are fanned out over a
pub/sub channel, so additional backend instances can participate. Live SSE
channels remain process-local (a single backend instance terminates a given
WebSocket connection); in production run one backend replica per sticky
session or a single replica, which is what docker-compose does.
"""
from __future__ import annotations

import asyncio
import json

from app.config import settings


class Broker:
    def __init__(self) -> None:
        self.backend = settings.resolved_queue_backend
        self.redis = None
        self._listener: asyncio.Task | None = None
        self.worker_out: dict[int, "asyncio.Queue[dict]"] = {}
        self.task_channels: dict[str, "asyncio.Queue[dict]"] = {}
        self.pending: dict[str, list[str]] = {}
        self.online: set[int] = set()

    # ----------------------------- lifecycle -----------------------------
    async def startup(self) -> None:
        if self.backend == "redis":
            import redis.asyncio as aioredis

            self.redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            self._listener = asyncio.create_task(self._listen())

    async def shutdown(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
        if self.redis is not None:
            await self.redis.aclose()

    async def _listen(self) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe("humanllm:notify:*")
        async for msg in pubsub.listen():
            if msg.get("type") != "pmessage":
                continue
            try:
                data = json.loads(msg["data"])
                await self._deliver_new_task(data["model"], data["task_id"])
            except Exception:
                continue

    async def _deliver_new_task(self, model: str, task_id: str) -> None:
        for wid in list(self.online):
            q = self.worker_out.get(wid)
            if q is not None:
                q.put_nowait({"type": "new_task", "model": model, "task_id": task_id})

    # --------------------------- worker registry ---------------------------
    def add_worker(self, worker_id: int) -> None:
        if worker_id not in self.worker_out:
            self.worker_out[worker_id] = asyncio.Queue()
        self.online.add(worker_id)

    def remove_worker(self, worker_id: int) -> None:
        self.online.discard(worker_id)
        self.worker_out.pop(worker_id, None)

    def out_queue(self, worker_id: int) -> "asyncio.Queue[dict] | None":
        return self.worker_out.get(worker_id)

    def send_to_worker(self, worker_id: int, msg: dict) -> bool:
        q = self.worker_out.get(worker_id)
        if q is None:
            return False
        q.put_nowait(msg)
        return True

    # ----------------------------- task channels ---------------------------
    def register_task(self, task_id: str) -> "asyncio.Queue[dict]":
        q: "asyncio.Queue[dict]" = asyncio.Queue()
        self.task_channels[task_id] = q
        return q

    def unregister_task(self, task_id: str) -> None:
        self.task_channels.pop(task_id, None)

    def publish_event(self, task_id: str, event: dict) -> None:
        q = self.task_channels.get(task_id)
        if q is not None:
            q.put_nowait(event)

    async def consume(self, task_id: str, timeout: float):
        """Yield events posted to the task channel until a terminal event or timeout."""
        q = self.task_channels.get(task_id)
        if q is None:
            return
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout)
            except asyncio.TimeoutError:
                yield {"type": "timeout"}
                return
            yield ev
            if ev.get("type") in ("done", "error", "cancelled", "timeout"):
                return

    # ------------------------------ pending queue --------------------------
    async def enqueue_pending(self, model: str, task_id: str) -> None:
        self.pending.setdefault(model, [])
        if task_id not in self.pending[model]:
            self.pending[model].append(task_id)
        if self.redis is not None:
            await self.redis.rpush(f"humanllm:pending:{model}", task_id)
            await self.redis.publish(
                f"humanllm:notify:{model}",
                json.dumps({"model": model, "task_id": task_id}),
            )

    async def remove_pending(self, model: str, task_id: str) -> None:
        if model in self.pending and task_id in self.pending[model]:
            self.pending[model].remove(task_id)
        if self.redis is not None:
            await self.redis.lrem(f"humanllm:pending:{model}", 0, task_id)

    def pending_for(self, model: str) -> list[str]:
        return list(self.pending.get(model, []))

    def pending_for_any(self, models: list[str]) -> list[str]:
        out: list[str] = []
        for m in models:
            out.extend(self.pending.get(m, []))
        return out

    async def notify_new_task(
        self, model: str, task_id: str, candidate_worker_ids: list[int]
    ) -> None:
        for wid in candidate_worker_ids:
            q = self.worker_out.get(wid)
            if q is not None:
                q.put_nowait({"type": "new_task", "model": model, "task_id": task_id})
        if self.redis is not None:
            await self.redis.publish(
                f"humanllm:notify:{model}",
                json.dumps({"model": model, "task_id": task_id}),
            )


broker = Broker()

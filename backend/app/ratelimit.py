"""In-process sliding-window rate limiter.

Anti-brute-force / anti-abuse core. Keeps the project dependency-free by using
an in-memory window; a single-process uvicorn worker is sufficient for most
deployments. (For multi-worker / multi-host, swap the bucket store for Redis —
the public API `check()` is the only thing callers depend on.)

Design:
  - Each ``key`` (e.g. "login:ip:1.2.3.4", "chat:key:42", "global:ip:...") owns
    a deque of request timestamps.
  - ``check(key, limit, window)`` drops timestamps older than ``window``
    seconds, then allows the request if the remaining count < limit.
  - No ``await`` inside ``check`` so it runs atomically between coroutine
    switch points (CPython GIL + single event loop), plus a ``threading.Lock``
    for belt-and-suspenders safety across the lifespan.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float) -> tuple[bool, int, float]:
        """Return ``(allowed, remaining, retry_after_seconds)``.

        ``retry_after_seconds`` is the time until the oldest in-window request
        expires (0 when allowed).
        """
        now = time.monotonic()
        with self._lock:
            dq = self._buckets[key]
            while dq and dq[0] <= now - window:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = max(0.0, dq[0] + window - now)
                return False, 0, retry_after
            dq.append(now)
            remaining = limit - len(dq)
            return True, remaining, 0.0

    def reset(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


# Shared singleton used across the app.
limiter = RateLimiter()

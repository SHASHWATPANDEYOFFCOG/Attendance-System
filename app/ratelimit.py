"""In-process rate limiting and client-IP resolution.

A sliding-window counter per (bucket, key). In-process is the right size for a single-campus
deployment running one API process; behind several processes, put the same limits in the
reverse proxy as well.

Client IP: the Next.js frontend proxies every browser call, so `request.client.host` is the
frontend server, not the student's phone. `X-Forwarded-For` is honoured **only** when the direct
peer is a trusted proxy (`ATTENDANCE_TRUSTED_PROXIES`, default loopback); otherwise anyone could
pick their own IP and dodge the limit.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status

_TRUSTED = {
    p.strip()
    for p in os.environ.get("ATTENDANCE_TRUSTED_PROXIES", "127.0.0.1,::1,localhost,testclient")
    .split(",")
    if p.strip()
}


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in _TRUSTED:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64] or peer
    return peer


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: Dict[Tuple[str, str], Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, window_s: float) -> float:
        """Record a hit. Returns 0 if allowed, else seconds until the next slot frees up."""
        now = time.monotonic()
        k = (bucket, key)
        with self._lock:
            q = self._hits.setdefault(k, deque())
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return max(0.0, window_s - (now - q[0]))
            q.append(now)
            if len(self._hits) > 50_000:          # bound memory under a key-spraying attack
                for stale in [kk for kk, dq in self._hits.items() if not dq][:10_000]:
                    self._hits.pop(stale, None)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindow()

# (limit, window seconds). Generous enough for a classroom of students behind one campus NAT,
# tight enough to stop scripted guessing.
LIMITS = {
    "login": (30, 60.0),
    "otp": (10, 600.0),
    "password_reset": (5, 900.0),
    "signup": (10, 3600.0),
    "attendance": (30, 60.0),
    "face": (60, 60.0),
}


def enforce(request: Request, bucket: str, key: str | None = None) -> None:
    """Raise 429 when `bucket` is exhausted for this client (and optional extra key)."""
    if os.environ.get("ATTENDANCE_DISABLE_RATE_LIMIT") == "1":
        return
    limit, window = LIMITS[bucket]
    who = client_ip(request) + (f"|{key}" if key else "")
    wait = limiter.hit(bucket, who, limit, window)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {int(wait) + 1} seconds.",
            headers={"Retry-After": str(int(wait) + 1)},
        )


def rate_limited(bucket: str):
    """FastAPI dependency form."""
    def _dep(request: Request) -> None:
        enforce(request, bucket)
    return _dep

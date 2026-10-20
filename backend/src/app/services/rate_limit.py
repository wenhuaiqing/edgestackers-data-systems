"""In-process rate limiting for the anonymous endpoints that cost something:
the triage agent (LLM calls) and replay (a pipeline run).

The demo runs as a single replica, so a process-local sliding window is
enough. The global gate is the cost circuit-breaker; the per-IP gate stops
one visitor spending it. Counters reset when the replica scales to zero,
which is fine - the goal is to make quota burn uneconomic, not to bill.

Client IP: behind nginx and the Container Apps ingress, both of which append
to X-Forwarded-For; the rightmost public address is the one the ingress saw,
so a client cannot spoof it by prepending entries.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from src.app.services.auth import has_write_token
from src.settings import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        cutoff = now - self.window
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    for raw in reversed([p.strip() for p in forwarded.split(",") if p.strip()]):
        try:
            if ipaddress.ip_address(raw).is_global:
                return raw
        except ValueError:
            continue
    return request.client.host if request.client else "unknown"


_window = settings.rate_limit_window_seconds
_triage_ip = SlidingWindowLimiter(settings.triage_rate_limit_per_ip, _window)
_triage_global = SlidingWindowLimiter(settings.triage_rate_limit_global, _window)
_replay_ip = SlidingWindowLimiter(settings.replay_rate_limit_per_ip, _window)


def _refuse(detail: str) -> None:
    raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(int(_window))})


async def limit_triage(request: Request) -> None:
    if has_write_token(request):
        return
    if not _triage_global.check("global"):
        _refuse("The triage agent has hit its ceiling for now. The graded results above are from the last full run.")
    if not _triage_ip.check(client_ip(request)):
        _refuse("Too many triage runs from this address. Please try again in a few minutes.")


async def limit_replay(request: Request) -> None:
    if has_write_token(request):
        return
    if not _replay_ip.check(client_ip(request)):
        _refuse("Too many replays from this address. Please try again in a few minutes.")

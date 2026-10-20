"""Request timings, kept in memory: the last 5,000 API calls this replica
served. They reset when it scales to zero - which the Operations page says,
rather than pretending to be a metrics store.
"""

from __future__ import annotations

import threading
import time
from collections import deque

_buf: deque[tuple[float, str, int, float]] = deque(maxlen=5000)
_lock = threading.Lock()
STARTED = time.time()


def record(path: str, status: int, ms: float) -> None:
    with _lock:
        _buf.append((time.time(), path, status, ms))


def summary() -> list[dict]:
    with _lock:
        data = list(_buf)
    by: dict[str, list[tuple[int, float]]] = {}
    for _, path, status, ms in data:
        by.setdefault(path, []).append((status, ms))
    out = []
    for path, vals in sorted(by.items()):
        ms = sorted(v for _, v in vals)
        out.append({
            "path": path, "calls": len(ms),
            "p50_ms": round(ms[len(ms) // 2], 1),
            "p95_ms": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 1),
            "max_ms": round(ms[-1], 1),
            "errors": sum(1 for s, _ in vals if s >= 500),
            "refused": sum(1 for s, _ in vals if 400 <= s < 500),
        })
    return out

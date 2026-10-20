"""Shared-secret gate for the demo's write paths.

The public demo has no user accounts. Anything that changes state - approving
a contract version, promoting a model, resetting the demo - is gated on one
secret sent as `X-Write-Token`. The operator unlocks a browser session by
visiting once with `?write_token=<value>`; the frontend keeps it in
sessionStorage and adds the header to every call.

Fail closed: no token configured means writes are refused everywhere.

Authority comes from the token. The actor name (`X-Actor`) is recorded and
used for separation of duties - the proposer of a change may not approve it -
but never trusted as identity on its own.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from src.settings import settings

HEADER = "x-write-token"


def has_write_token(request: Request) -> bool:
    configured = settings.demo_write_token
    supplied = request.headers.get(HEADER, "")
    if not configured or not supplied:
        return False
    return hmac.compare_digest(configured.encode("utf-8"), supplied.encode("utf-8"))


async def require_write_token(request: Request) -> None:
    if not settings.demo_write_token:
        raise HTTPException(status_code=403,
                            detail="Writes are disabled on this deployment (no DEMO_WRITE_TOKEN configured).")
    if not has_write_token(request):
        raise HTTPException(status_code=401,
                            detail="This action needs the operator's write token. The public link is read-only.")


def actor(request: Request) -> str:
    name = (request.headers.get("x-actor") or "operator").strip()[:40]
    return name or "operator"

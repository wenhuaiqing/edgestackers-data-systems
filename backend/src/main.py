"""FastAPI application entry."""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from src.app.pipeline import reference as ref
from src.app.routers import actions, pages, workflow
from src.app.services import analytics, db, llm, timings
from src.settings import settings

app = FastAPI(
    title="tapeline",
    description="Raw market events to decisions you can trust. All market data is synthetic.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def time_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        route = request.scope.get("route")
        timings.record(getattr(route, "path", request.url.path), response.status_code,
                       (time.perf_counter() - t0) * 1000)
    return response


app.include_router(pages.router)
app.include_router(workflow.router)
app.include_router(actions.router)


@app.get("/health")
def health() -> dict[str, str]:
    db.connection()
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict[str, object]:
    """What this deployment has - the UI sets expectations from it."""
    return {
        "version": settings.git_sha or "dev",
        "uptime_seconds": int(time.time() - timings.STARTED),
        "synthetic_data": True,
        "week": [ref.TRADING_DAYS[0].isoformat(), ref.TRADING_DAYS[-1].isoformat()],
        "timezone": ref.TZ_LABEL,
        "llm_configured": llm.configured(),
        "llm_model": settings.llm_chat_model if llm.configured() else None,
        "writes_enabled": bool(settings.demo_write_token),
        "counts": analytics.meta_counts(),
        "build_seconds": db.kv("build_seconds"),
    }

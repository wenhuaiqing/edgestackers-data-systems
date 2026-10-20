"""Read endpoints, one per page. Thin: the SQL lives in services/analytics.py."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.app.services import analytics, timings

router = APIRouter(prefix="/api", tags=["pages"])


@router.get("/overview")
def overview() -> dict:
    return analytics.overview()


@router.get("/feeds")
def feeds() -> dict:
    return analytics.feeds()


@router.get("/pipeline")
def pipeline() -> dict:
    return analytics.pipeline()


@router.get("/lineage")
def lineage(instrument: str, minute: str) -> dict:
    try:
        return analytics.lineage(instrument, minute)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/bars")
def bars(instrument: str, day: str) -> dict:
    return analytics.bars_day(instrument, day)


@router.get("/quality")
def quality() -> dict:
    return analytics.quality()


@router.get("/quarantine")
def quarantine(check: str | None = None, venue: str | None = None, day: str | None = None,
               limit: int = Query(200, le=500)) -> list[dict]:
    return analytics.quarantine_rows(check, venue, day, limit)


@router.get("/incidents")
def incidents() -> dict:
    return analytics.incidents()


@router.get("/decisions")
def decisions() -> dict:
    return analytics.decisions()


@router.get("/orders")
def orders(instrument: str | None = None, day: str | None = None, model: str = "mr-v1",
           limit: int = Query(300, le=1000)) -> list[dict]:
    return analytics.orders(instrument, day, model, limit)


@router.get("/ablation")
def ablation() -> dict:
    return analytics.ablation()


@router.get("/operations")
def operations() -> dict:
    return analytics.operations(timings.summary())

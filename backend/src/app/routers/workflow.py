"""Governed writes. Token-gated; the rules live in services/workflow.py."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from src.app.services import workflow
from src.app.services.auth import actor, require_write_token

router = APIRouter(prefix="/api", tags=["workflow"], dependencies=[Depends(require_write_token)])


class Decision(BaseModel):
    note: str = Field(default="", max_length=400)


@router.post("/proposals/{proposal_id}/approve")
async def approve(proposal_id: str, body: Decision, request: Request) -> dict:
    # Reprocessing the week takes seconds; keep the event loop free meanwhile.
    return await asyncio.to_thread(workflow.decide_proposal, proposal_id, actor(request), True, body.note)


@router.post("/proposals/{proposal_id}/reject")
async def reject(proposal_id: str, body: Decision, request: Request) -> dict:
    return await asyncio.to_thread(workflow.decide_proposal, proposal_id, actor(request), False, body.note)


@router.post("/models/{model_id}/promote")
async def promote(model_id: str, request: Request) -> dict:
    return await asyncio.to_thread(workflow.promote, model_id, actor(request))


@router.post("/reset")
async def reset(request: Request) -> dict:
    return await asyncio.to_thread(workflow.reset, actor(request))

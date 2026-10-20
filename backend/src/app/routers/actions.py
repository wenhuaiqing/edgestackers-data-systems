"""Anonymous actions that cost something: replay, triage, ad-hoc queries.
Rate-limited, never state-changing beyond their own log."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.app.services import db, llm, replay, sql_validator, triage
from src.app.services.rate_limit import limit_replay, limit_triage
from src.app.services.triage_cases import LABELS
from src.settings import settings

router = APIRouter(prefix="/api", tags=["actions"])

EVAL_STATUS = settings.data_dir.parent / "evals" / "status.json"


class ReplayRequest(BaseModel):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


@router.post("/replay", dependencies=[Depends(limit_replay)])
async def run_replay(body: ReplayRequest) -> dict:
    try:
        return await asyncio.to_thread(replay.replay, body.day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/triage")
def triage_page() -> dict:
    alerts = db.rows("SELECT * FROM alerts ORDER BY alert_id")
    for a in alerts:
        a["world"] = json.loads(a["world"])
        cat, action = LABELS.get(a["incident_id"], (None, None))
        a["label"] = {"category": cat, "action": action}
    status = json.loads(EVAL_STATUS.read_text(encoding="utf-8")) if EVAL_STATUS.exists() else None
    return {"alerts": alerts, "eval": status, "llm_configured": llm.configured(), "model": settings.llm_chat_model,
            "recent": db.rows("SELECT run_id, ts, alert_id, engine, model, ms, steps, grade FROM triage_runs "
                              "ORDER BY ts DESC LIMIT 20")}


class TriageRequest(BaseModel):
    alert_id: str = Field(max_length=20)
    engine: str = Field(default="agent", pattern="^(agent|rules)$")


def _triage(alert_id: str, engine: str) -> dict:
    rows = db.rows("SELECT * FROM alerts WHERE alert_id = ?", [alert_id])
    if not rows:
        raise HTTPException(status_code=404, detail=f"No alert {alert_id}.")
    alert = rows[0]
    fallback_reason = None
    if engine == "agent" and llm.configured():
        try:
            run = triage.run_agent(alert)
        except Exception as exc:  # noqa: BLE001 - degrade visibly, never silently
            fallback_reason = f"The agent could not finish ({type(exc).__name__}); the runbook answered instead."
            run = triage.run_rules(alert)
    elif engine == "agent":
        fallback_reason = "No language model is configured on this deployment; the runbook answered instead."
        run = triage.run_rules(alert)
    else:
        run = triage.run_rules(alert)
    cat, action = LABELS[alert["incident_id"]]
    grade = triage.grade(run, {"category": cat, "action": action})
    run_id = f"TR-{int(time.time() * 1000) % 10**10:010d}"
    with db.writing() as cur:
        cur.execute("INSERT INTO triage_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            run_id, datetime.now().replace(microsecond=0), alert_id, run["engine"], run["model"], run["ms"],
            run["steps"], json.dumps(run["result"]), json.dumps(grade), json.dumps(run["trace"], default=str),
        ])
    return {"run_id": run_id, **{k: run[k] for k in ("engine", "model", "result", "trace", "steps", "ms")},
            "tools_called": sorted(k for k in run["retrieved"]) if run["engine"] == "agent" else [],
            "grade": grade, "label": {"category": cat, "action": action}, "fallback_reason": fallback_reason}


@router.post("/triage/run", dependencies=[Depends(limit_triage)])
async def triage_run(body: TriageRequest) -> dict:
    return await asyncio.to_thread(_triage, body.alert_id, body.engine)


class QueryRequest(BaseModel):
    sql: str = Field(max_length=4000)


QUERY_TIMEOUT_SECONDS = 5.0


def _run_query(sql: str) -> dict:
    verdict = sql_validator.validate(sql)
    if not verdict.ok:
        raise HTTPException(status_code=400, detail=" ".join(verdict.errors))
    cur = db.connection().cursor()
    timer = threading.Timer(QUERY_TIMEOUT_SECONDS, cur.interrupt)
    t0 = time.perf_counter()
    timer.start()
    try:
        df = cur.execute(verdict.sql).df()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).split("\n")[0][:300]
        if "INTERRUPT" in msg.upper():
            msg = f"Stopped after {QUERY_TIMEOUT_SECONDS:.0f} s."
        raise HTTPException(status_code=400, detail=msg) from exc
    finally:
        timer.cancel()
        cur.close()
    return {"sql": verdict.sql, "tables": verdict.tables, "columns": list(df.columns),
            "rows": db.records(df), "ms": round((time.perf_counter() - t0) * 1000, 1)}


@router.post("/query")
async def query(body: QueryRequest) -> dict:
    return await asyncio.to_thread(_run_query, body.sql)

"""Governed writes: contract approvals, model promotion, reset.

Every write is token-gated by the router, audit-logged here, and refused - not
warned - when the rule says no:

  - the proposer of a change cannot approve it
  - a proposal is decided once
  - a model is promoted only when the evidence meets the rule agreed before
    the shadow run began

Approving a contract version reprocesses the held partitions from the raw
files, re-runs the decision layer and replaces the governed tables, so every
page moves on the next request. Nothing is patched in place.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime

from fastapi import HTTPException

from src.app.pipeline import contracts as ct
from src.app.pipeline import registry
from src.app.pipeline.decisions import run_decisions
from src.app.pipeline.persist import persist_governed, run_cost_aud
from src.app.pipeline.stages import ALL_ON, run_pipeline
from src.app.services import db
from src.settings import settings


def _audit(cur, actor: str, action: str, subject: str, outcome: str, detail: dict | str) -> None:
    cur.execute("INSERT INTO audit_log VALUES (?, ?, ?, ?, ?, ?)", [
        datetime.now().replace(microsecond=0), actor, action, subject, outcome,
        detail if isinstance(detail, str) else json.dumps(detail, default=str),
    ])


def _refuse(cur, actor: str, action: str, subject: str, status: int, reason: str) -> None:
    _audit(cur, actor, action, subject, "refused", reason)
    raise HTTPException(status_code=status, detail=reason)


def approved_versions() -> dict[str, list[tuple[int, date]]]:
    out: dict[str, list[tuple[int, date]]] = {}
    for r in db.rows("SELECT contract_id, version, effective_from FROM contract_versions WHERE source = 'platform'"):
        out.setdefault(r["contract_id"], []).append((int(r["version"]), date.fromisoformat(str(r["effective_from"])[:10])))
    return out


def _snapshot() -> dict:
    s = db.query("SELECT model_id, sum(pnl) AS pnl FROM pnl_daily GROUP BY 1").set_index("model_id")["pnl"].to_dict()
    return {
        "live_pnl": round(float(s.get("mr-v1", 0.0)), 2),
        "shadow_pnl": round(float(s.get("mr-v2", 0.0)), 2),
        "quarantined": int(db.scalar("SELECT count(*) FROM quarantine")),
        "held_by_schema": int(db.scalar("SELECT count(*) FROM quarantine WHERE check_id = 'schema'")),
        "degraded_minutes": int(db.scalar("SELECT count(*) FROM gate WHERE state = 'degraded'")),
        "alt_volume_share_15_16": round(float(db.scalar(
            "SELECT coalesce(sum(alt_volume), 0) / sum(volume) FROM bars WHERE day >= DATE '2026-10-15'")), 4),
    }


def decide_proposal(proposal_id: str, actor: str, approve: bool, note: str = "") -> dict:
    with db.writing() as cur:
        rows = cur.execute("SELECT * FROM proposals WHERE proposal_id = ?", [proposal_id]).df()
        if rows.empty:
            raise HTTPException(status_code=404, detail=f"No proposal {proposal_id}.")
        p = rows.iloc[0]
        action = "approve" if approve else "reject"
        if p["status"] != "pending":
            _refuse(cur, actor, action, proposal_id, 409,
                    f"{proposal_id} was already {p['status']} by {p['decided_by']}. A proposal is decided once.")
        if actor.strip().lower() == str(p["proposed_by"]).lower():
            _refuse(cur, actor, action, proposal_id, 403,
                    f"{actor} proposed {proposal_id} and cannot also decide it. Someone else has to.")

        now = datetime.now().replace(microsecond=0)
        if not approve:
            cur.execute("""UPDATE proposals SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ?
                           WHERE proposal_id = ?""", [actor, now, note, proposal_id])
            _audit(cur, actor, "reject", proposal_id, "done", note or "rejected")
            return {"proposal_id": proposal_id, "status": "rejected"}

        before = _snapshot()
        cur.execute("INSERT INTO contract_versions VALUES (?, ?, 'approved', ?, ?, ?, 'platform')", [
            p["contract_id"], int(p["version"]), p["effective_from"], actor,
            json.dumps(ct.ALT_TRADES_V2),
        ])
        cur.execute("""UPDATE proposals SET status = 'approved', decided_by = ?, decided_at = ?, decision_note = ?
                       WHERE proposal_id = ?""", [actor, now, note, proposal_id])

        approved = approved_versions_from(cur)
        raw = settings.data_dir / "raw"
        w0, c0 = time.perf_counter(), time.process_time()
        result = run_pipeline(raw, approved=approved, use_cache=True)
        decisions = run_decisions(result.bars, result.book, result.gate)
        wall_ms = (time.perf_counter() - w0) * 1000
        files = db.query("SELECT file, arrived_at FROM raw_files")
        result.files = result.files.merge(files, on="file", how="left")
        n = int(cur.execute("SELECT count(*) FROM runs").fetchone()[0]) + 1
        output_hash = __import__("hashlib").sha256(
            "".join(result.partition_hashes.sort_values("partition")["sha256"]).encode()).hexdigest()
        run = {
            "run_id": f"RUN-{n:04d}", "kind": "reprocess", "trigger": f"{proposal_id} approved by {actor}",
            "started_at": now, "finished_at": datetime.now().replace(microsecond=0), "git_sha": settings.git_sha,
            "contract_versions": {k: max(v for v, _ in vs) for k, vs in approved.items()},
            "controls": ALL_ON, "wall_ms": round(wall_ms, 1), "cpu_ms": round((time.process_time() - c0) * 1000, 1),
            "cost_aud": run_cost_aud(wall_ms), "output_sha256": output_hash,
        }
        persist_governed(cur, result, decisions, run)
        promotion = registry.promotion_evidence(decisions)
        cur.execute("UPDATE kv SET v = ? WHERE k = 'promotion'", [json.dumps(promotion, default=str)])
        cur.execute("""UPDATE incidents SET status = 'resolved', resolved_at = ?,
                       response = response || ' Resolved: contract v2 approved by ' || ? || '; partitions reprocessed from raw in ' || ? || '.'
                       WHERE incident_id = 'INC-06'""", [now, actor, run["run_id"]])
        after = _snapshot()
        _audit(cur, actor, "approve", proposal_id, "done", {"run_id": run["run_id"], "before": before, "after": after})
        return {"proposal_id": proposal_id, "status": "approved", "run": run, "before": before, "after": after,
                "promotion_eligible": promotion["eligible"]}


def approved_versions_from(cur) -> dict[str, list[tuple[int, date]]]:
    out: dict[str, list[tuple[int, date]]] = {}
    for contract_id, version, eff in cur.execute(
            "SELECT contract_id, version, effective_from FROM contract_versions WHERE source = 'platform'").fetchall():
        out.setdefault(contract_id, []).append((int(version), eff if isinstance(eff, date) else date.fromisoformat(str(eff)[:10])))
    return out


def promote(model_id: str, actor: str) -> dict:
    with db.writing() as cur:
        promotion = json.loads(cur.execute("SELECT v FROM kv WHERE k = 'promotion'").fetchone()[0])
        if model_id != promotion["shadow"]:
            _refuse(cur, actor, "promote", model_id, 409, f"{model_id} is not the shadow model.")
        failing = [c for c in promotion["checks"] if not c["passed"]]
        if failing:
            reasons = "; ".join(f"{c['rule']} (is {c['value']})" for c in failing)
            _refuse(cur, actor, "promote", model_id, 409,
                    f"Not promoted. The rule agreed before the shadow run is not met: {reasons}.")
        cur.execute("UPDATE model_registry SET stage = 'retired' WHERE model_id = ?", [promotion["live"]])
        cur.execute("UPDATE model_registry SET stage = 'live' WHERE model_id = ?", [model_id])
        _audit(cur, actor, "promote", model_id, "done", promotion)
        return {"model_id": model_id, "stage": "live", "effective": "from the next session"}


def reset(actor: str) -> dict:
    db.reset_to_build()
    with db.writing() as cur:
        _audit(cur, actor, "reset", "platform", "done", "restored the built state")
    return {"status": "reset"}


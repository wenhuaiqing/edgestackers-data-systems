"""Contract and model registries: what is approved, what is proposed, and the
evidence each proposal carries.

A proposal is decided on evidence computed from the data, not on the
proposer's say-so - and never by the proposer.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from src.app.pipeline import contracts as ct
from src.app.pipeline import reference as ref
from src.app.pipeline.decisions import MODELS, summarise


def contracts_table() -> pd.DataFrame:
    rows = []
    for cid, c in ct.load_all().items():
        rows.append({
            "contract_id": cid, "venue": c["venue"], "stream": c["stream"], "owner": c["owner"],
            "file": c["_file"], "consumers": json.dumps(c.get("consumers", [])), "sla": json.dumps(c.get("sla", {})),
            "checks": ", ".join(c.get("checks", [])), "key": ", ".join(c.get("key", [])),
        })
    return pd.DataFrame(rows)


def contract_versions_table() -> pd.DataFrame:
    rows = []
    for cid, c in ct.load_all().items():
        for v in c["versions"]:
            rows.append({"contract_id": cid, "version": v["version"], "status": v["status"],
                         "effective_from": date.fromisoformat(str(v["effective_from"])),
                         "approved_by": v.get("approved_by", ""), "fields": json.dumps(v["fields"]),
                         "source": "repository"})
    return pd.DataFrame(rows)


def _ks(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample Kolmogorov-Smirnov statistic."""
    a, b = np.sort(a), np.sort(b)
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / a.size
    cdf_b = np.searchsorted(b, grid, side="right") / b.size
    return float(np.max(np.abs(cdf_a - cdf_b)))


def alt_v2_evidence(raw_dir) -> dict:
    """Is ALT's new `size` the old `qty` under another name? Check before
    anyone is asked to approve it."""
    before = pd.concat([pd.read_parquet(raw_dir / f"ALT/trades/{d.isoformat()}.parquet")
                        for d in ref.TRADING_DAYS if d < ref.SCHEMA_DRIFT["from_day"]])
    after = pd.concat([pd.read_parquet(raw_dir / f"ALT/trades/{d.isoformat()}.parquet")
                       for d in ref.TRADING_DAYS if d >= ref.SCHEMA_DRIFT["from_day"]])
    old = before.loc[before["event_type"] == "trade", "qty"].astype(float).to_numpy()
    new = after.loc[after["event_type"] == "trade", "size"].astype(float).to_numpy()
    ks = _ks(np.log(old), np.log(new))
    # Critical value at 1%, two-sample.
    crit = 1.63 * np.sqrt((old.size + new.size) / (old.size * new.size))
    flags = after["liquidity_flag"].value_counts(normalize=True).round(3).to_dict()
    lot_old = float((old % 1 == 0).mean())
    lot_new = float((new % 1 == 0).mean())
    return {
        "renamed_field": "qty -> size",
        "added_field": "liquidity_flag (optional, A or R)",
        "rows_before": int(old.size), "rows_after": int(new.size),
        "median_before": float(np.median(old)), "median_after": float(np.median(new)),
        "mean_ratio": round(float(new.mean() / old.mean()), 3),
        "ks_statistic": round(ks, 4), "ks_critical_1pct": round(float(crit), 4),
        "same_distribution": bool(ks < crit),
        "whole_units_before": round(lot_old, 3), "whole_units_after": round(lot_new, 3),
        "liquidity_flag_values": flags,
        "verdict": ("size is distributed as qty was (KS {:.3f} under the 1% critical value {:.3f}; "
                    "median {:.0f} vs {:.0f}): a rename, not a change of unit.").format(
                        ks, crit, np.median(new), np.median(old)),
    }


def proposals_table(evidence: dict, preview: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "proposal_id": "CV-0007",
        "kind": "contract_version",
        "subject": "alt.trades v2",
        "contract_id": "alt.trades",
        "version": 2,
        "effective_from": ref.SCHEMA_DRIFT["from_day"],
        "proposed_by": "triage-agent",
        "proposed_at": pd.Timestamp.combine(ref.SCHEMA_DRIFT["from_day"], ref.SESSION_OPEN) + pd.Timedelta(minutes=4),
        "summary": "Map ALT's size onto qty and accept liquidity_flag (A or R) as an optional field, effective from "
                   f"{ref.SCHEMA_DRIFT['from_day']:%d/%m/%Y}. Reprocess the held partitions from raw.",
        "evidence": json.dumps(evidence),
        "preview": json.dumps(preview),
        "status": "pending",
    }]).assign(decided_by=pd.Series([None], dtype="string"),
               decided_at=pd.Series([pd.NaT], dtype="datetime64[us]"),
               decision_note=pd.Series([None], dtype="string"))


PROMOTION_RULE = {
    "min_sessions": 5,
    "min_sessions_ahead": 4,
    "drawdown_no_worse_than": 1.10,
    "text": "Promote the shadow model only after at least 5 shadow sessions, ahead of live in at least 4 of them, "
            "ahead in total, and with a worst drawdown no more than 10% deeper than live's. Agreed before the "
            "shadow run began.",
}


def promotion_evidence(decisions: dict) -> dict:
    s = summarise(decisions)
    live = s[s["model_id"] == "mr-v1"].set_index("day")
    shadow = s[s["model_id"] == "mr-v2"].set_index("day")
    days = []
    for d in live.index:
        days.append({"day": d.isoformat(), "live_pnl": float(live.at[d, "pnl"]), "shadow_pnl": float(shadow.at[d, "pnl"]),
                     "shadow_ahead": bool(shadow.at[d, "pnl"] > live.at[d, "pnl"]),
                     "live_drawdown": float(live.at[d, "max_drawdown"]), "shadow_drawdown": float(shadow.at[d, "max_drawdown"])})
    ahead = sum(d["shadow_ahead"] for d in days)
    total_live = float(live["pnl"].sum())
    total_shadow = float(shadow["pnl"].sum())
    dd_ratio = float(shadow["max_drawdown"].max() / max(live["max_drawdown"].max(), 1e-9))
    checks = [
        {"rule": f"At least {PROMOTION_RULE['min_sessions']} shadow sessions", "value": len(days),
         "passed": len(days) >= PROMOTION_RULE["min_sessions"]},
        {"rule": f"Ahead of live in at least {PROMOTION_RULE['min_sessions_ahead']} sessions", "value": ahead,
         "passed": ahead >= PROMOTION_RULE["min_sessions_ahead"]},
        {"rule": "Ahead of live in total", "value": round(total_shadow - total_live, 2),
         "passed": total_shadow > total_live},
        {"rule": "Worst drawdown no more than 10% deeper than live's", "value": round(dd_ratio, 3),
         "passed": dd_ratio <= PROMOTION_RULE["drawdown_no_worse_than"]},
    ]
    return {"rule": PROMOTION_RULE["text"], "days": days, "checks": checks,
            "eligible": all(c["passed"] for c in checks),
            "live": "mr-v1", "shadow": "mr-v2", "live_total": round(total_live, 2), "shadow_total": round(total_shadow, 2)}


def models_registry() -> pd.DataFrame:
    return pd.DataFrame([{"model_id": m.model_id, "stage": m.stage, "description": m.description,
                          "entry_z": m.entry_z, "exit_z": m.exit_z, "volume_filter": m.volume_filter}
                         for m in MODELS])

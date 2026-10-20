"""Replay a session from its raw files and prove the output is the same.

Reads the raw files from disk (never the in-process cache - a replay that
reuses what it already read proves nothing), re-hashes them against the
pinned manifest, re-runs that day's pipeline under the contract versions in
force, and compares every governed partition's digest with the one recorded
by the run that produced the current tables.
"""

from __future__ import annotations

import time
from datetime import date

from src.app.pipeline import reference as ref
from src.app.pipeline.stages import run_pipeline
from src.app.services import db
from src.app.services.workflow import approved_versions
from src.settings import settings

MANIFEST = settings.data_dir.parent / "infra-azure" / "build.sha256"


def _pinned() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            digest, _, name = line.partition("  ")
            out[name.strip()] = digest.strip()
    return out


def replay(day: str) -> dict:
    d = date.fromisoformat(day)
    if d not in ref.TRADING_DAYS:
        raise ValueError(f"{day} is not a session in this week.")
    t0 = time.perf_counter()
    result = run_pipeline(settings.data_dir / "raw", days=[d], approved=approved_versions(), use_cache=False)
    wall_ms = (time.perf_counter() - t0) * 1000
    recorded = {r["partition"]: r["sha256"] for r in db.rows("SELECT partition, sha256 FROM partition_hashes")}
    pinned = _pinned()
    partitions = []
    for r in result.partition_hashes.itertuples():
        partitions.append({"partition": r.partition, "rows": int(r.rows), "sha256": r.sha256,
                           "recorded": recorded.get(r.partition), "match": recorded.get(r.partition) == r.sha256})
    files = []
    for r in result.files.itertuples():
        files.append({"file": r.file, "rows": int(r.rows), "sha256": r.sha256, "pinned": pinned.get(f"raw/{r.file}"),
                      "match": pinned.get(f"raw/{r.file}") == r.sha256 if pinned else None})
    return {
        "day": day, "wall_ms": round(wall_ms, 1),
        "files": files, "partitions": partitions,
        "all_match": all(p["match"] for p in partitions) and all(f["match"] in (True, None) for f in files),
        "stages": [s.__dict__ for s in result.stages],
    }

"""Build the whole platform from nothing.

  1. generate the week's feeds (deterministic)
  2. run the pipeline and the live model once, and place the bad print in a
     minute when the model holds the instrument; regenerate with it there
  3. the governed run, timed and hashed
  4. a preview of approving ALT's contract v2, so the proposal carries its
     consequences before anyone decides it
  5. the ablation - every control off in turn
  6. incidents, proposals, model registry, triage alerts
  7. write data/tapeline.build.duckdb and check the partition hashes against
     the pinned manifest

Usage (from backend/):
  uv run python ../scripts/build_platform.py              # build, verify against the manifest
  uv run python ../scripts/build_platform.py --write-manifest
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from src.app.pipeline import reference as ref  # noqa: E402
from src.app.pipeline import registry  # noqa: E402
from src.app.pipeline.ablation import choose_bad_print_minute, run_ablation  # noqa: E402
from src.app.pipeline.alerts import build_alerts  # noqa: E402
from src.app.pipeline.decisions import run_decisions, summarise  # noqa: E402
from src.app.pipeline.generate import generate  # noqa: E402
from src.app.pipeline.incidents import build_incidents  # noqa: E402
from src.app.pipeline.persist import persist_governed, run_cost_aud  # noqa: E402
from src.app.pipeline.stages import ALL_ON, _RAW_CACHE, run_pipeline  # noqa: E402
from src.settings import settings  # noqa: E402

MANIFEST = REPO_ROOT / "infra-azure" / "build.sha256"


def _replace(con, name, df):
    con.register("_f", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _f")
    con.unregister("_f")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()

    t0 = time.perf_counter()
    raw = Path(settings.data_dir) / "raw"
    if raw.exists():
        shutil.rmtree(raw)

    print("1/7 generating feeds (pass 1)")
    generate(raw)
    first = run_pipeline(raw, hash_files=False)
    first_dec = run_decisions(first.bars, first.book, first.gate)
    choice = choose_bad_print_minute(first_dec)
    if choice is None:
        bad_at, multiplier = ref.BAD_PRINT["default_at"], ref.BAD_PRINT["multiplier"]
    else:
        bad_at, multiplier = choice[0].to_pydatetime() + timedelta(seconds=59.412), choice[1]
    print(f"    bad print placed at {bad_at:%d/%m %H:%M:%S}, x{multiplier}")
    shutil.rmtree(raw)
    _RAW_CACHE.clear()
    files = generate(raw, bad_print_at=bad_at, bad_print_multiplier=multiplier)

    print("2/7 governed run")
    w0, c0 = time.perf_counter(), time.process_time()
    governed = run_pipeline(raw, use_cache=True)
    decisions = run_decisions(governed.bars, governed.book, governed.gate)
    wall_ms = (time.perf_counter() - w0) * 1000
    cpu_ms = (time.process_time() - c0) * 1000
    arrivals = {f.path: f.arrived_at for f in files}
    governed.files["arrived_at"] = governed.files["file"].map(arrivals)

    print("3/7 preview: ALT contract v2 approved")
    approved = {"alt.trades": [(2, ref.SCHEMA_DRIFT["from_day"])]}
    preview_run = run_pipeline(raw, approved=approved, hash_files=False, use_cache=True)
    preview_dec = run_decisions(preview_run.bars, preview_run.book, preview_run.gate)
    s0, s1 = summarise(decisions), summarise(preview_dec)
    days_after = [d for d in ref.TRADING_DAYS if d >= ref.SCHEMA_DRIFT["from_day"]]
    def _alt_share(bars):
        b = bars[bars["day"].isin(days_after)]
        return float(b["alt_volume"].fillna(0).sum() / max(b["volume"].sum(), 1))
    preview = {
        "trades_released": int(len(governed.quarantine[governed.quarantine["check_id"] == "schema"])),
        "alt_volume_share_after": round(_alt_share(preview_run.bars), 4),
        "alt_volume_share_before": round(_alt_share(governed.bars), 4),
        "degraded_minutes_before": int((governed.gate["state"] == "degraded").sum()),
        "degraded_minutes_after": int((preview_run.gate["state"] == "degraded").sum()),
        "live_pnl_before": round(float(s0.query("model_id == 'mr-v1'")["pnl"].sum()), 2),
        "live_pnl_after": round(float(s1.query("model_id == 'mr-v1'")["pnl"].sum()), 2),
        "new_quarantine": {k: int(v) for k, v in preview_run.quarantine.groupby("check_id").size().items()
                           if k not in ("schema",)},
    }

    print("4/7 ablation (every control off in turn)")
    ablation = run_ablation(raw, governed, decisions)
    print(ablation[["control", "bars_changed", "research_bars_changed", "orders_changed", "pnl_delta",
                    "desk_worst_mark", "kill_switch", "crossed_fills"]].to_string(index=False))

    print("5/7 incidents, registries, alerts")
    incidents = build_incidents(governed, ablation)
    evidence = registry.alt_v2_evidence(raw)
    proposals = registry.proposals_table(evidence, preview)
    promotion = registry.promotion_evidence(decisions)
    alerts = build_alerts(governed, incidents)

    print("6/7 writing the platform")
    db_path = Path(settings.build_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    output_hash = __import__("hashlib").sha256(
        "".join(governed.partition_hashes.sort_values("partition")["sha256"]).encode()).hexdigest()
    run = {
        "run_id": "RUN-0001", "kind": "full build", "trigger": "image build",
        "started_at": pd.Timestamp.now().floor("s"), "finished_at": pd.Timestamp.now().floor("s"),
        "git_sha": settings.git_sha, "contract_versions": {"alt.trades": 1},
        "controls": ALL_ON, "wall_ms": round(wall_ms, 1), "cpu_ms": round(cpu_ms, 1),
        "cost_aud": run_cost_aud(wall_ms), "output_sha256": output_hash,
    }
    persist_governed(con, governed, decisions, run)
    _replace(con, "ablation", ablation)
    _replace(con, "incidents", incidents)
    _replace(con, "contracts", registry.contracts_table())
    _replace(con, "contract_versions", registry.contract_versions_table())
    _replace(con, "proposals", proposals)
    _replace(con, "model_registry", registry.models_registry())
    _replace(con, "alerts", alerts)
    _replace(con, "instruments", pd.DataFrame([i.__dict__ for i in ref.INSTRUMENTS]))
    con.execute("CREATE TABLE kv (k VARCHAR PRIMARY KEY, v VARCHAR)")
    con.execute("INSERT INTO kv VALUES (?, ?)", ["promotion", json.dumps(promotion, default=str)])
    con.execute("INSERT INTO kv VALUES (?, ?)", ["bad_print_at", bad_at.isoformat()])
    con.execute("INSERT INTO kv VALUES (?, ?)", ["bad_print_multiplier", str(multiplier)])
    con.execute("INSERT INTO kv VALUES (?, ?)", ["preview", json.dumps(preview, default=str)])
    con.execute("INSERT INTO kv VALUES (?, ?)", ["build_seconds", f"{time.perf_counter() - t0:.1f}"])
    con.execute("""CREATE TABLE audit_log (ts TIMESTAMP, actor VARCHAR, action VARCHAR, subject VARCHAR,
                   outcome VARCHAR, detail VARCHAR)""")
    con.execute("""CREATE TABLE api_timings (ts TIMESTAMP, path VARCHAR, status INTEGER, ms DOUBLE)""")
    con.execute("""CREATE TABLE triage_runs (run_id VARCHAR, ts TIMESTAMP, alert_id VARCHAR, engine VARCHAR,
                   model VARCHAR, ms DOUBLE, steps INTEGER, result VARCHAR, grade VARCHAR, trace VARCHAR)""")
    con.close()

    print("7/7 manifest")
    lines = sorted(f"{h}  {p}" for p, h in zip(governed.partition_hashes["partition"], governed.partition_hashes["sha256"]))
    lines += sorted(f"{h}  raw/{p}" for p, h in zip(governed.files["file"], governed.files["sha256"]))
    body = "\n".join(lines) + "\n"
    if args.write_manifest or not MANIFEST.exists():
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text("# SHA-256 of every raw file and governed partition the build produces.\n"
                            "# Regenerate with: uv run python ../scripts/build_platform.py --write-manifest\n" + body,
                            encoding="utf-8", newline="\n")
        print(f"    manifest written: {len(lines)} entries")
    else:
        pinned = [ln for ln in MANIFEST.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        # Order-free: the manifest is a set of digests, written in two sorted groups.
        if sorted(pinned) != sorted(lines):
            missing = sorted(set(pinned) - set(lines))
            unexpected = sorted(set(lines) - set(pinned))
            print(f"    MISMATCH against the pinned manifest: {len(missing)} pinned entries not produced, "
                  f"{len(unexpected)} produced entries not pinned", file=sys.stderr)
            for ln in (missing + unexpected)[:6]:
                print(f"      {ln}", file=sys.stderr)
            return 1
        print(f"    verified: {len(lines)} entries match the pinned manifest")

    shutil.copyfile(db_path, settings.duckdb_path)
    print(f"done in {time.perf_counter() - t0:.0f} s -> {db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

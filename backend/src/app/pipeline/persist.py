"""Write a governed run into the platform's DuckDB.

Used by the build and again whenever an approval reprocesses data, so the
tables the pages read always come from one code path.
"""

from __future__ import annotations

import json
from datetime import datetime

import duckdb
import pandas as pd

from src.app.pipeline.decisions import MODELS, round_trips, summarise
from src.app.pipeline.stages import PipelineResult

GOVERNED_TABLES = ["raw_files", "trades", "quotes", "quarantine", "bars", "book", "gate", "restatements",
                   "clock_offsets", "partition_hashes", "orders", "equity", "pnl_daily", "round_trips",
                   "kill_switch"]


def _replace(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("_frame", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _frame")
    con.unregister("_frame")


def persist_governed(con: duckdb.DuckDBPyConnection, result: PipelineResult, decisions: dict,
                     run: dict) -> None:
    trades = result.trades.drop(columns=["known_from", "instrument_id"], errors="ignore")
    quotes = result.quotes[["event_id", "file", "raw_row", "venue", "day", "symbol", "instrument_key", "ts_exchange",
                            "ts_received", "ts_available", "bid", "bid_size", "ask", "ask_size", "status"]]
    _replace(con, "raw_files", result.files)
    _replace(con, "trades", trades)
    _replace(con, "quotes", quotes)
    _replace(con, "quarantine", result.quarantine)
    _replace(con, "bars", result.bars)
    _replace(con, "book", result.book)
    _replace(con, "gate", result.gate)
    _replace(con, "restatements", result.restatements)
    _replace(con, "clock_offsets", result.clock_offsets)
    _replace(con, "partition_hashes", result.partition_hashes.assign(run_id=run["run_id"]))
    orders = decisions["orders"].copy()
    orders.insert(0, "order_id", [f"O-{i + 1:05d}" for i in range(len(orders))])
    _replace(con, "orders", orders)
    _replace(con, "equity", decisions["equity"])
    _replace(con, "pnl_daily", summarise(decisions))
    _replace(con, "round_trips", round_trips(decisions["orders"]))
    _replace(con, "kill_switch", decisions["kill_switch"])
    _replace(con, "models", pd.DataFrame([m.__dict__ for m in MODELS]))

    con.execute("""CREATE TABLE IF NOT EXISTS runs (
        run_id VARCHAR, kind VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, git_sha VARCHAR,
        trigger VARCHAR, contract_versions VARCHAR, controls VARCHAR, wall_ms DOUBLE, cpu_ms DOUBLE,
        cost_aud DOUBLE, output_sha256 VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS run_stages (
        run_id VARCHAR, seq INTEGER, stage VARCHAR, rows_in BIGINT, rows_out BIGINT, quarantined BIGINT,
        wall_ms DOUBLE, cpu_ms DOUBLE, note VARCHAR)""")
    con.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        run["run_id"], run["kind"], run["started_at"], run["finished_at"], run.get("git_sha", ""),
        run.get("trigger", ""), json.dumps(run.get("contract_versions", {})), json.dumps(run.get("controls", {})),
        run["wall_ms"], run["cpu_ms"], run["cost_aud"], run["output_sha256"],
    ])
    for seq, st in enumerate(result.stages):
        con.execute("INSERT INTO run_stages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            run["run_id"], seq, st.name, st.rows_in, st.rows_out, st.quarantined, st.wall_ms, st.cpu_ms, st.note,
        ])


# Container Apps consumption, list price, australiaeast, converted at 1.52.
# The free grant would cover a demo's runs entirely; list price is what the
# number means at scale.
VCPU_SECOND_AUD = 0.000024 * 1.52
GIB_SECOND_AUD = 0.000003 * 1.52


def run_cost_aud(wall_ms: float, vcpu: float = 0.75, gib: float = 1.5) -> float:
    seconds = wall_ms / 1000.0
    return round(seconds * (vcpu * VCPU_SECOND_AUD + gib * GIB_SECOND_AUD), 6)


def now() -> datetime:
    return datetime.now().replace(microsecond=0)

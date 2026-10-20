"""Validator for SQL typed on the Query page. SELECT-only, allowlisted
tables, LIMIT enforced.

The connection already has external access off, so this is the second layer,
not the only one. It exists because "the database will stop it" is not an
answer anyone should accept on its own for a public text box.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ALLOWED_TABLES = {
    "trades", "quotes", "quarantine", "bars", "book", "gate", "restatements", "clock_offsets",
    "raw_files", "partition_hashes", "orders", "equity", "pnl_daily", "round_trips", "kill_switch",
    "incidents", "ablation", "instruments", "runs", "run_stages", "contracts", "contract_versions",
    "model_registry", "alerts",
}

FORBIDDEN = {
    "insert", "update", "delete", "drop", "truncate", "alter", "create", "attach", "detach", "copy",
    "export", "import", "pragma", "set", "call", "grant", "revoke", "merge", "vacuum", "install", "load",
    "checkpoint", "reset", "use", "describe", "summarize",
}
FORBIDDEN_FUNCTIONS = re.compile(r"\b(read_\w+|glob|parquet_\w+|duckdb_\w+|query_table|query|getenv|sniff_csv)\s*\(", re.I)

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000


@dataclass
class Verdict:
    ok: bool
    sql: str
    errors: list[str]
    tables: list[str]


def _strip(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", "", sql)
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL).strip()


def validate(sql: str) -> Verdict:
    errors: list[str] = []
    body = _strip(sql).rstrip(";").strip()
    if not body:
        return Verdict(False, sql, ["Empty query."], [])
    if ";" in body:
        errors.append("One statement at a time.")
    first = body.split(None, 1)[0].lower()
    if first not in ("select", "with"):
        errors.append("Only SELECT (or WITH ... SELECT) is allowed.")
    words = {w.lower() for w in re.findall(r"[A-Za-z_]+", body)}
    bad = sorted(words & FORBIDDEN)
    if bad:
        errors.append(f"Not allowed here: {', '.join(bad)}.")
    if FORBIDDEN_FUNCTIONS.search(body):
        errors.append("File, URL and catalogue functions are not allowed.")
    ctes = {m.lower() for m in re.findall(r"(?:with|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", body, flags=re.I)}
    referenced = {m.lower() for m in re.findall(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_\.]*)", body, flags=re.I)}
    unknown = sorted(t for t in referenced if t not in ALLOWED_TABLES and t not in ctes)
    if unknown:
        errors.append(f"Unknown or private table: {', '.join(unknown)}. Allowed: {', '.join(sorted(ALLOWED_TABLES))}.")
    limit = re.search(r"\blimit\s+(\d+)\s*$", body, flags=re.I)
    if limit:
        if int(limit.group(1)) > MAX_LIMIT:
            body = body[: limit.start()] + f"LIMIT {MAX_LIMIT}"
    else:
        body = f"SELECT * FROM ({body}) AS q LIMIT {DEFAULT_LIMIT}"
    return Verdict(not errors, body, errors, sorted(referenced & ALLOWED_TABLES))

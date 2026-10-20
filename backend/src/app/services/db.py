"""The platform's DuckDB: one process-wide connection, cursors per request.

The build writes data/edgestackers.build.duckdb; the app works on a copy, so a
reset is a file copy and the built state is never lost. Writes - approvals,
reprocessing, the audit log - take the write lock; reads use their own cursor
and never wait for anything but DuckDB itself.

External access is switched off at connect, so no query - including one a
visitor writes on the Query page - can read a file or a URL.
"""

from __future__ import annotations

import shutil
import threading
from contextlib import contextmanager
from typing import Any

import duckdb
import pandas as pd

from src.settings import settings

_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.RLock()
WRITE_LOCK = threading.Lock()


def _connect() -> duckdb.DuckDBPyConnection:
    path = settings.duckdb_path
    if not path.exists():
        if not settings.build_db_path.exists():
            raise RuntimeError("No platform database. Run scripts/build_platform.py first.")
        shutil.copyfile(settings.build_db_path, path)
    con = duckdb.connect(str(path))
    con.execute("SET enable_external_access = false")
    return con


def connection() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            _con = _connect()
        return _con


def available() -> bool:
    try:
        connection()
        return True
    except Exception:  # noqa: BLE001
        return False


def query(sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    cur = connection().cursor()
    try:
        return cur.execute(sql, params or []).df()
    finally:
        cur.close()


def rows(sql: str, params: list[Any] | None = None) -> list[dict]:
    return records(query(sql, params))


def scalar(sql: str, params: list[Any] | None = None) -> Any:
    cur = connection().cursor()
    try:
        row = cur.execute(sql, params or []).fetchone()
        return row[0] if row else None
    finally:
        cur.close()


def kv(key: str) -> str | None:
    return scalar("SELECT v FROM kv WHERE k = ?", [key])


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame to JSON-safe records: NaN and NaT become null, timestamps ISO."""
    out = df.astype(object).where(pd.notna(df), None)
    recs = out.to_dict(orient="records")
    for r in recs:
        for k, v in r.items():
            if isinstance(v, pd.Timestamp):
                r[k] = v.isoformat()
            elif hasattr(v, "isoformat"):
                r[k] = v.isoformat()
            elif hasattr(v, "item"):
                r[k] = v.item()
    return recs


@contextmanager
def writing():
    """Serialise writers. DuckDB is single-writer; so is this demo."""
    with WRITE_LOCK:
        cur = connection().cursor()
        try:
            yield cur
        finally:
            cur.close()


def reset_to_build() -> None:
    """Throw away every approval and write: back to the built state."""
    global _con
    with WRITE_LOCK, _lock:
        if _con is not None:
            _con.close()
            _con = None
        shutil.copyfile(settings.build_db_path, settings.duckdb_path)
        _con = _connect()

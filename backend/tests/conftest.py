"""Shared fixtures.

The suite runs against the built platform (scripts/build_platform.py). Tests
that write work on a throwaway copy of the database, never the built one.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_TMP = Path(tempfile.mkdtemp(prefix="tapeline-tests-"))
# Point the app at a scratch copy before any src module reads settings.
os.environ["DUCKDB_PATH"] = str(_TMP / "tapeline.duckdb")
os.environ.setdefault("DEMO_WRITE_TOKEN", "test-token")
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""

from src.app.pipeline import reference as ref  # noqa: E402
from src.app.pipeline.decisions import run_decisions  # noqa: E402
from src.app.pipeline.stages import run_pipeline  # noqa: E402
from src.settings import settings  # noqa: E402

RAW = settings.data_dir / "raw"


def pytest_collection_modifyitems(config, items):
    if not settings.build_db_path.exists() or not RAW.exists():
        skip = pytest.mark.skip(reason="build the platform first: uv run python ../scripts/build_platform.py")
        for item in items:
            if "needs_build" in item.keywords:
                item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_build: requires data/ from scripts/build_platform.py")


@pytest.fixture(scope="session")
def governed():
    return run_pipeline(RAW, use_cache=True)


@pytest.fixture(scope="session")
def governed_decisions(governed):
    return run_decisions(governed.bars, governed.book, governed.gate)


@pytest.fixture()
def fresh_db():
    """A clean copy of the built database for a test that writes."""
    from src.app.services import db
    db.reset_to_build()
    yield db
    db.reset_to_build()


def pytest_sessionfinish(session, exitstatus):
    from src.app.services import db
    try:
        if db._con is not None:
            db._con.close()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(_TMP, ignore_errors=True)


__all__ = ["ref", "RAW"]

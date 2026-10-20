"""The decision layer reads bars as first published and stops at the loss
limit."""

from __future__ import annotations

import numpy as np
import pytest

from src.app.pipeline.decisions import DESK_LOSS_LIMIT, run_decisions
from src.app.pipeline.stages import run_pipeline

from .conftest import RAW

pytestmark = pytest.mark.needs_build


def test_decisions_never_read_a_restated_bar(governed, governed_decisions):
    bars = governed.bars.copy()
    rng = np.random.default_rng(1)
    for col in ("close", "vwap", "volume", "high", "low", "open"):
        bars[col] = bars[col] * rng.uniform(0.5, 1.5, len(bars))
    again = run_decisions(bars, governed.book, governed.gate)
    a = governed_decisions["orders"].reset_index(drop=True)
    b = again["orders"].reset_index(drop=True)
    assert a.equals(b), "changing only the final (restated) fields must not change a single order"


def test_loss_limit_flattens_and_stops_the_desk():
    variant = run_pipeline(RAW, controls={"price_band": False}, hash_files=False, use_cache=True)
    dec = run_decisions(variant.bars, variant.book, variant.gate)
    kills = dec["kill_switch"]
    live = kills[kills["model_id"] == "mr-v1"]
    assert len(live) == 1
    at = live["triggered_at"].iloc[0]
    eq = dec["equity"]
    desk = eq[eq["model_id"] == "mr-v1"].groupby("minute")["equity"].sum()
    assert desk.loc[at] < -DESK_LOSS_LIMIT
    o = dec["orders"]
    after = o[(o["model_id"] == "mr-v1") & (o["decided_at"] > at) & (o["executed_at"].dt.date == at.date())]
    assert set(after["reason"]) <= {"kill switch: desk loss limit", "flat at the close"}

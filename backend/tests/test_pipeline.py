"""Every seeded defect is found, from the data alone, and handled as the
contracts say."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.app.pipeline import reference as ref
from src.app.pipeline.generate import generate
from src.app.pipeline.stages import run_pipeline

from .conftest import RAW

pytestmark = pytest.mark.needs_build


def test_generator_is_deterministic(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a)
    generate(b)
    for f in sorted(a.rglob("*.parquet")):
        other = b / f.relative_to(a)
        assert hashlib.sha256(f.read_bytes()).hexdigest() == hashlib.sha256(other.read_bytes()).hexdigest(), f


def test_dedupe_drops_resends_and_is_idempotent(governed):
    q = governed.quarantine[governed.quarantine["check_id"] == "duplicate_trade_id"]
    assert len(q) > 100
    assert set(q["venue"]) == {"ALT"} and set(q["day"]) == {ref.DUP_BURST["day"]}
    dups = governed.trades[governed.trades["status"] == "duplicate"]
    kept = governed.trades[(governed.trades["source"] == "ALT") & (governed.trades["status"] == "accepted")]
    assert dups["trade_id"].isin(kept["trade_id"]).all(), "every dropped copy has its first copy kept"
    again = run_pipeline(RAW, days=[ref.DUP_BURST["day"]], use_cache=True)
    recorded = governed.partition_hashes.set_index("partition")["sha256"]
    for row in again.partition_hashes.itertuples():
        assert recorded[row.partition] == row.sha256


def test_arbitration_fills_gaps_by_trade_id(governed):
    t = governed.trades
    fills = t[t["flags"].str.contains("gap_fill", na=False) & (t["event_type"] == "trade")]
    assert len(fills) > 400
    direct = set(t.loc[t["source"] == "PRIMARY", "trade_id"])
    assert not fills["trade_id"].isin(direct).any()
    in_gap = np.zeros(len(fills), dtype=bool)
    for g in ref.FEED_GAPS:
        in_gap |= ((fills["ts_exchange"] >= pd.Timestamp(g["start"])) & (fills["ts_exchange"] < pd.Timestamp(g["end"]))).to_numpy()
    assert in_gap.all(), "the vendor copy is used only where PRIMARY has a gap"


def test_bad_print_never_reaches_a_bar(governed):
    held = governed.quarantine[governed.quarantine["check_id"] == "price_band"]
    assert len(held) == 1
    trade = governed.trades.set_index("event_id").loc[held["event_id"].iloc[0]]
    assert trade["status"] == "cancelled" and "cancel_while_held" in trade["flags"]
    minute = pd.Timestamp(trade["ts_exchange"]).floor("min")
    bar = governed.bars[(governed.bars["instrument_key"] == trade["instrument_key"]) & (governed.bars["minute"] == minute)].iloc[0]
    assert bar["pub_high"] < trade["price"] / 2 or trade["price"] < bar["pub_low"] / 2
    blocked = governed.gate[(governed.gate["instrument_key"] == trade["instrument_key"]) & (governed.gate["state"] == "blocked")]
    assert minute in set(blocked["minute"])


def test_genuine_move_is_released(governed):
    kosc = ref.INSTRUMENT_BY_SYMBOL[ref.GENUINE_MOVE["symbol"]].instrument_id
    t = governed.trades[governed.trades["instrument_key"] == kosc]
    assert t["flags"].str.contains("band_confirmed").sum() >= 3
    q = governed.quarantine
    assert not ((q["check_id"] == "price_band") & (q["instrument_key"] == kosc)).any()


def test_clock_offset_measured_and_bounded(governed):
    co = governed.clock_offsets.set_index("day")
    for day in ref.TRADING_DAYS:
        expected = ref.VENDOR_SKEW["offset_ms"] if day >= ref.VENDOR_SKEW["from"].date() else 0.0
        assert co.loc[day, "applied_ms"] == expected
        assert co.loc[day, "negative_latency_after"] == 0
    assert (co["mad_ms"] <= 20).all()


def test_symbol_change_keeps_one_instrument(governed):
    sc = ref.SYMBOL_CHANGE
    bars = governed.bars
    assert not bars["instrument_key"].isin([sc["old"], sc["new"]]).any()
    days = set(bars.loc[bars["instrument_key"] == sc["instrument_id"], "day"])
    assert set(ref.TRADING_DAYS) <= days
    held = governed.quarantine[governed.quarantine["check_id"] == "symbol_known"]
    assert (held["resolved_at"] == pd.Timestamp(sc["master_arrives"])).all()


def test_schema_drift_quarantines_the_partition(governed):
    q = governed.quarantine[governed.quarantine["check_id"] == "schema"]
    assert set(q["venue"]) == {"ALT"}
    assert set(q["day"]) == {d for d in ref.TRADING_DAYS if d >= ref.SCHEMA_DRIFT["from_day"]}
    approved = run_pipeline(RAW, days=[ref.SCHEMA_DRIFT["from_day"]], use_cache=True,
                            approved={"alt.trades": [(2, ref.SCHEMA_DRIFT["from_day"])]})
    assert not (approved.quarantine["check_id"] == "schema").any()
    assert (approved.trades["source"] == "ALT").sum() > 1000


def test_crossed_quotes_never_price_a_fill(governed, governed_decisions):
    q = governed.quotes
    assert (q.loc[q["bid"] >= q["ask"], "status"] == "crossed").all()
    orders = governed_decisions["orders"].merge(governed.book, left_on=["instrument_key", "executed_at"],
                                                right_on=["instrument_key", "minute"], how="left")
    alt_crossed = governed.quarantine[governed.quarantine["check_id"] == "crossed_book"]
    minutes = set(zip(alt_crossed["instrument_key"], alt_crossed["ts_exchange"].dt.floor("min")))
    hit = orders[[(k, m) in minutes for k, m in zip(orders["instrument_key"], orders["executed_at"])]]
    assert not (hit["crossed"].fillna(False)).any()

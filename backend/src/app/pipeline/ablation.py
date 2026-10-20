"""What each control is worth, measured rather than asserted.

Every control is switched off on its own, the week is re-run from the raw
files, and the result is compared with the governed run: bars that differ,
orders that differ, the live model's P&L, the desk's worst mark, and whether
the loss limit fired. One more run switches everything off at once.

Some controls earn their keep this week; some changed nothing. Both are
findings. A control that changed nothing is insurance, and insurance is a
cost/criticality call - which is the conversation the Trade-offs page has.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.app.pipeline import reference as ref
from src.app.pipeline.decisions import run_decisions, summarise
from src.app.pipeline.stages import CONTROLS, PipelineResult, run_pipeline

SYMBOL_TO_ID = {i.symbol: i.instrument_id for i in ref.INSTRUMENTS}
SYMBOL_TO_ID[ref.SYMBOL_CHANGE["new"]] = ref.SYMBOL_CHANGE["instrument_id"]


def _canonical_key(keys: pd.Series) -> pd.Series:
    return keys.map(lambda k: SYMBOL_TO_ID.get(k, k))


def _bar_view(bars: pd.DataFrame, prefix: str = "pub_") -> pd.DataFrame:
    cols = {f"{prefix}close": "close", f"{prefix}volume": "volume"}
    v = bars[["instrument_key", "minute", *cols]].rename(columns=cols).copy()
    v["instrument_key"] = _canonical_key(v["instrument_key"])
    return v.groupby(["instrument_key", "minute"], as_index=False).agg(close=("close", "last"), volume=("volume", "sum"))


def _bars_changed(base: pd.DataFrame, variant: pd.DataFrame, prefix: str) -> int:
    m = _bar_view(base, prefix).merge(_bar_view(variant, prefix), on=["instrument_key", "minute"], how="outer",
                                      suffixes=("_b", "_v"), indicator=True)
    differs = (m["_merge"] != "both") | ((m["close_b"] - m["close_v"]).abs() > 1e-9) | (
        (m["volume_b"].fillna(0) - m["volume_v"].fillna(0)).abs() > 1e-9)
    return int(differs.sum())


def _order_keys(orders: pd.DataFrame, model_id: str) -> set:
    if orders.empty:
        return set()
    o = orders[orders["model_id"] == model_id]
    keys = _canonical_key(o["instrument_key"])
    return set(zip(keys, o["executed_at"], o["side"], o["qty"]))


def _desk_worst(equity: pd.DataFrame, model_id: str) -> float:
    e = equity[equity["model_id"] == model_id]
    return float(e.groupby("minute")["equity"].sum().min()) if len(e) else 0.0


def compare(base: PipelineResult, base_dec: dict, variant: PipelineResult, var_dec: dict,
            model_id: str = "mr-v1") -> dict:
    ob, ov = _order_keys(base_dec["orders"], model_id), _order_keys(var_dec["orders"], model_id)
    sb, sv = summarise(base_dec), summarise(var_dec)
    pnl_b = float(sb.loc[sb["model_id"] == model_id, "pnl"].sum())
    pnl_v = float(sv.loc[sv["model_id"] == model_id, "pnl"].sum())
    kills = var_dec["kill_switch"]
    kills = kills[kills["model_id"] == model_id]
    crossed_fills = 0
    if len(var_dec["orders"]):
        o = var_dec["orders"]
        o = o[o["model_id"] == model_id].merge(variant.book, left_on=["instrument_key", "executed_at"],
                                                right_on=["instrument_key", "minute"], how="left")
        crossed_fills = int(o["crossed"].fillna(False).astype(bool).sum())
    return {
        "bars_changed": _bars_changed(base.bars, variant.bars, "pub_"),
        "research_bars_changed": _bars_changed(base.bars, variant.bars, ""),
        "orders_changed": int(len(ob ^ ov)),
        "pnl": round(pnl_v, 2),
        "pnl_delta": round(pnl_v - pnl_b, 2),
        "desk_worst_mark": round(_desk_worst(var_dec["equity"], model_id), 2),
        "kill_switch": "; ".join(f"{r.day:%d/%m} {r.triggered_at:%H:%M}" for r in kills.itertuples()) or "",
        "crossed_fills": crossed_fills,
        "quarantined": int(len(variant.quarantine)),
    }


def run_ablation(raw_dir: Path, base: PipelineResult, base_dec: dict, approved: dict | None = None) -> pd.DataFrame:
    rows = []
    variants = [(name, {name: False}) for name in CONTROLS]
    variants.append(("all_controls_off", {name: False for name in CONTROLS}))
    for name, controls in variants:
        var = run_pipeline(raw_dir, controls=controls, approved=approved, hash_files=False, use_cache=True)
        use_gate = controls.get("quality_gate", True)
        dec = run_decisions(var.bars, var.book, var.gate, use_gate=use_gate)
        row = {"control": name, "description": CONTROLS.get(name, "Every control off at once")}
        row.update(compare(base, base_dec, var, dec))
        rows.append(row)
    out = pd.DataFrame(rows)
    # The governed run itself fills some orders on a book crossed across
    # venues; what a control is worth is the change from that, not the count.
    base_crossed = compare(base, base_dec, base, base_dec)["crossed_fills"]
    out["crossed_fills_delta"] = out["crossed_fills"] - base_crossed
    out["governed_pnl"] = round(float(summarise(base_dec).query("model_id == 'mr-v1'")["pnl"].sum()), 2)
    out["governed_worst_mark"] = round(_desk_worst(base_dec["equity"], "mr-v1"), 2)
    return out


def choose_bad_print_minute(base_dec: dict) -> tuple[pd.Timestamp, float] | None:
    """A minute on the bad-print day when the live model holds the instrument
    and keeps holding it for at least three more minutes, and the multiplier
    that marks against that position.

    The defect is placed where it would hurt, the way real ones are found -
    not where it happens to land.
    """
    bp = ref.BAD_PRINT
    inst = ref.INSTRUMENT_BY_SYMBOL[bp["symbol"]].instrument_id
    eq = base_dec["equity"]
    e = eq[(eq["model_id"] == "mr-v1") & (eq["instrument_key"] == inst)].set_index("minute")["position"]
    lo, hi = pd.Timestamp(bp["window"][0]), pd.Timestamp(bp["window"][1])
    e = e[(e.index >= lo) & (e.index <= hi)]
    pos = e.to_numpy()
    for i in range(len(pos) - 3):
        run = pos[i:i + 4]
        if (run != 0).all() and (np.sign(run) == np.sign(run[0])).all():
            return e.index[i + 1], (10.0 if run[0] < 0 else 0.1)
    return None


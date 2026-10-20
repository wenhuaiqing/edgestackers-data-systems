"""Alerts and the snapshot each one carries for the triage agent.

When a check fires, the platform freezes what an investigator would look at
- samples, latency, cross-feed alignment, the contract diff, price context,
duplicates, the book, reference data, feed activity - into the alert. The
agent's tools read that snapshot. A triage can then be replayed and graded
exactly, which is what makes it measurable at all.

Every tool answers for every alert. Most answers are "nothing unusual";
choosing which to ask is part of the job.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from src.app.pipeline import contracts as ct
from src.app.pipeline import reference as ref
from src.app.pipeline.stages import BAND, PipelineResult

TOOL_NAMES = ["get_samples", "get_feed_latency", "get_cross_feed_alignment", "get_contract_diff",
              "get_price_context", "get_duplicate_stats", "get_book_state", "get_reference_data",
              "get_feed_activity"]


def _ts(v) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or pd.isna(v):
        return None
    return pd.Timestamp(v).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _clean(obj):
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime, np.datetime64)):
        return _ts(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if np.isnan(obj) else round(float(obj), 6)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def feed_latency(r: PipelineResult, source: str, day: date) -> dict:
    if source in ("PRIMARY", "ALT", "VENDOR"):
        t = r.trades[(r.trades["source"] == source) & (r.trades["day"] == day)]
        lat = (t["ts_received"] - t["ts_exchange_raw"]).dt.total_seconds() * 1000
    else:
        lat = pd.Series(dtype=float)
    if lat.empty:
        return {"source": source, "day": day, "events": 0, "note": "no trade events for this source on this day"}
    contract_p99 = ct.load_all()[f"{source.lower()}.trades"]["sla"]["freshness_p99_ms"]
    return {"source": source, "day": day, "events": int(len(lat)),
            "p50_ms": float(lat.quantile(0.5)), "p95_ms": float(lat.quantile(0.95)), "p99_ms": float(lat.quantile(0.99)),
            "negative_share": float((lat < -50).mean()), "beyond_watermark_share": float((lat > 3000).mean()),
            "contract_freshness_p99_ms": contract_p99}


def cross_feed_alignment(r: PipelineResult, day: date) -> dict:
    row = r.clock_offsets[r.clock_offsets["day"] == day]
    if row.empty:
        return {"day": day, "note": "no alignment measured"}
    x = row.iloc[0]
    return {"day": day, "compared": "VENDOR exchange time minus PRIMARY exchange time, same trade id",
            "matched_trades": int(x["matched"]), "median_ms": float(x["median_ms"]), "mad_ms": float(x["mad_ms"]),
            "full_day_median_ms": float(x["full_day_median_ms"]),
            "contract_tolerance": ct.load_all()["vendor.trades"]["clock_offset"]["apply_when"]}


def contract_diff(r: PipelineResult, venue: str, stream: str, day: date) -> dict:
    f = r.files[(r.files["venue"] == venue) & (r.files["stream"] == stream) & (r.files["day"] == day)]
    if f.empty:
        return {"venue": venue, "stream": stream, "day": day, "note": "no partition"}
    row = f.iloc[0]
    cid = f"{venue.lower()}.{stream}"
    observed = [c.strip() for c in row["fields"].split(",")]
    v = ct.judge(ct.load_all()[cid], 1, observed)
    return {"contract": cid, "version_in_force": int(row.get("version", 1)), "partition": row["file"],
            "fields_observed": observed, "missing_required": v.missing, "unknown_fields": v.unknown,
            "conforms": v.ok}


def price_context(r: PipelineResult, instrument_key: str | None, at: datetime | None) -> dict:
    if instrument_key is None or at is None:
        return {"note": "no instrument in this alert"}
    t = r.trades[(r.trades["instrument_key"] == instrument_key) & (r.trades["event_type"] == "trade")
                 & r.trades["status"].isin(["accepted", "held", "cancelled"])]
    at = pd.Timestamp(at)
    before = t[(t["ts_exchange"] >= at - pd.Timedelta(minutes=5)) & (t["ts_exchange"] < at)]
    window = t[(t["ts_exchange"] >= at - pd.Timedelta(seconds=180)) & (t["ts_exchange"] <= at + pd.Timedelta(seconds=180))]
    ref_px = float(before["price"].median()) if len(before) else float(window["price"].median())
    dev = window["price"] / ref_px - 1
    out = window.assign(dev=dev)
    per_venue = {}
    for venue, g in out.groupby("venue"):
        per_venue[venue] = {"prints": int(len(g)), "outside_band": int((g["dev"].abs() > BAND).sum()),
                            "max_deviation": float(g["dev"].abs().max()), "median_price": float(g["price"].median())}
    symbol = t["symbol"].iloc[0] if len(t) else None
    after = t[(t["ts_exchange"] > at + pd.Timedelta(seconds=60)) & (t["ts_exchange"] <= at + pd.Timedelta(minutes=10))]
    return {"instrument": instrument_key, "symbol": symbol, "around": at, "five_minute_median_before": ref_px,
            "band": BAND, "by_venue": per_venue,
            "median_price_1_to_10_min_after": float(after["price"].median()) if len(after) else None,
            "cancels_received": int(((r.trades["event_type"] == "trade_cancel")
                                     & r.trades["cancels_trade_id"].isin(window["trade_id"])).sum())}


def duplicate_stats(r: PipelineResult, venue: str, day: date) -> dict:
    t = r.trades[(r.trades["source"] == venue) & (r.trades["day"] == day) & (r.trades["event_type"] == "trade")]
    counts = t.groupby("trade_id").size()
    repeated = counts[counts > 1]
    dups = t[t["trade_id"].isin(repeated.index)]
    if dups.empty:
        return {"venue": venue, "day": day, "repeated_trade_ids": 0}
    later = dups.sort_values("ts_received").groupby("trade_id").nth(1)
    return {"venue": venue, "day": day, "repeated_trade_ids": int(len(repeated)),
            "copies_beyond_first": int(repeated.sum() - len(repeated)),
            "repeat_received_from": later["ts_received"].min(), "repeat_received_to": later["ts_received"].max(),
            "original_exchange_times_from": dups["ts_exchange"].min(), "original_exchange_times_to": dups["ts_exchange"].max(),
            "same_price_and_qty_on_every_copy": bool(
                dups.groupby("trade_id")[["price", "qty"]].nunique().max().max() == 1),
            "example": {"trade_id": repeated.index[0],
                        "event_ids": list(t.loc[t["trade_id"] == repeated.index[0], "event_id"])}}


def book_state(r: PipelineResult, venue: str, day: date, start: datetime | None, end: datetime | None) -> dict:
    q = r.quotes[(r.quotes["venue"] == venue) & (r.quotes["day"] == day)] if venue in ("PRIMARY", "ALT") else r.quotes.iloc[0:0]
    if start is not None:
        q = q[(q["ts_exchange"] >= pd.Timestamp(start) - pd.Timedelta(minutes=5))
              & (q["ts_exchange"] <= pd.Timestamp(end or start) + pd.Timedelta(minutes=5))]
    crossed = q[q["bid"] >= q["ask"]]
    out = {"venue": venue, "day": day, "quotes_examined": int(len(q)), "crossed_quotes": int(len(crossed))}
    if len(crossed):
        out.update({
            "crossed_from": crossed["ts_exchange"].min(), "crossed_to": crossed["ts_exchange"].max(),
            "symbols": sorted(crossed["symbol"].unique().tolist()),
            "example": crossed.iloc[0][["symbol", "ts_exchange", "bid", "ask"]].to_dict(),
            "other_venue_crossed": int((r.quotes[(r.quotes["venue"] != venue) & (r.quotes["day"] == day)]
                                        .eval("bid >= ask")).sum()),
        })
    return out


def reference_data(r: PipelineResult, symbol: str | None, day: date) -> dict:
    sc = ref.SYMBOL_CHANGE
    known = r.trades[(r.trades["day"] == day)]
    syms = sorted(known["symbol"].dropna().unique().tolist())
    arrived = sc["master_arrives"] if day == sc["effective"] else datetime.combine(day, datetime.min.time()) + timedelta(hours=6)
    out = {"day": day, "symbol_master_arrived_at": arrived, "contract_arrives_by": "09:30",
           "symbols_traded": len(syms)}
    if symbol:
        row = r.trades[(r.trades["symbol"] == symbol) & (r.trades["day"] == day)]
        held = row["flags"].str.contains("held_unknown_symbol", na=False)
        out.update({"symbol": symbol, "events_today": int(len(row)), "events_held_unknown": int(held.sum()),
                    "instrument_after_master": row["instrument_key"].dropna().iloc[0] if row["instrument_key"].notna().any() else None})
        if symbol == sc["new"]:
            out["previous_symbol_for_instrument"] = sc["old"]
    return out


def feed_activity(r: PipelineResult, day: date, start: datetime | None, end: datetime | None) -> dict:
    if start is None:
        return {"day": day, "note": "no window in this alert"}
    s = pd.Timestamp(start) - pd.Timedelta(minutes=3)
    e = pd.Timestamp(end or start) + pd.Timedelta(minutes=3)
    t = r.trades[(r.trades["day"] == day) & (r.trades["event_type"] == "trade")
                 & (r.trades["ts_exchange"] >= s) & (r.trades["ts_exchange"] < e)]
    t = t.assign(minute=t["ts_exchange"].dt.floor("min").dt.strftime("%H:%M"))
    direct = t[t["source"] == "PRIMARY"].groupby("minute").size()
    vendor = t[t["source"] == "VENDOR"].groupby("minute").size()
    vendor_only = t[(t["source"] == "VENDOR") & t["flags"].str.contains("gap_fill", na=False)].groupby("minute").size()
    alt = t[t["source"] == "ALT"].groupby("minute").size()
    minutes = sorted(set(direct.index) | set(vendor.index) | set(alt.index))
    return {"day": day, "window": [s, e], "per_minute": [
        {"minute": m, "primary_direct": int(direct.get(m, 0)), "vendor": int(vendor.get(m, 0)),
         "vendor_only": int(vendor_only.get(m, 0)), "alt": int(alt.get(m, 0))} for m in minutes]}


def samples(rows: pd.DataFrame, cols: list[str], n: int = 5) -> list[dict]:
    keep = [c for c in cols if c in rows.columns]
    return [_clean(r) for r in rows[keep].head(n).to_dict(orient="records")]


def _world(r, *, venue, stream, day, instrument=None, symbol=None, at=None, start=None, end=None, sample_rows=None,
           sample_cols=None, latency_source=None) -> dict:
    return _clean({
        "get_samples": samples(sample_rows, sample_cols or []) if sample_rows is not None else [],
        "get_feed_latency": feed_latency(r, latency_source or (venue if venue != "REF" else "PRIMARY"), day),
        "get_cross_feed_alignment": cross_feed_alignment(r, day),
        "get_contract_diff": contract_diff(r, venue if venue != "VENDOR" or stream == "trades" else venue, stream, day),
        "get_price_context": price_context(r, instrument, at),
        "get_duplicate_stats": duplicate_stats(r, venue if venue in ("PRIMARY", "ALT") else "PRIMARY", day),
        "get_book_state": book_state(r, venue if venue in ("PRIMARY", "ALT") else "PRIMARY", day, start or at, end),
        "get_reference_data": reference_data(r, symbol, day),
        "get_feed_activity": feed_activity(r, day, start or at, end),
    })


TRADE_COLS = ["event_id", "source", "symbol", "trade_id", "ts_exchange", "ts_received", "price", "qty", "side", "flags"]


def build_alerts(r: PipelineResult, incidents: pd.DataFrame) -> pd.DataFrame:
    q, t = r.quarantine, r.trades
    rows = []
    for inc in incidents.itertuples():
        day = pd.Timestamp(inc.started_at).date()
        if inc.incident_id == "INC-01":
            d = q[q["check_id"] == "duplicate_trade_id"]
            sample = t[t["event_id"].isin(d["event_id"])]
            world = _world(r, venue="ALT", stream="trades", day=day, start=inc.started_at, sample_rows=sample, sample_cols=TRADE_COLS)
            summary = f"duplicate_trade_id fired {len(d)} times on ALT trades"
        elif inc.incident_id in ("INC-02", "INC-03"):
            gap = next(g for g in ref.FEED_GAPS if g["day"] == day)
            sample = t[t["flags"].str.contains("gap_fill", na=False) & (t["day"] == day)]
            world = _world(r, venue="PRIMARY", stream="trades", day=day, start=gap["start"], end=gap["end"],
                           sample_rows=sample, sample_cols=TRADE_COLS)
            summary = "feed_gap: the vendor feed is carrying PRIMARY trades the direct feed has not delivered"
        elif inc.incident_id == "INC-04":
            sample = t[(t["source"] == "VENDOR") & (t["day"] == day)].assign(
                latency_ms=lambda x: (x["ts_received"] - x["ts_exchange_raw"]).dt.total_seconds() * 1000)
            sample = sample[sample["latency_ms"] < -50].assign(ts_exchange=lambda x: x["ts_exchange_raw"])
            world = _world(r, venue="VENDOR", stream="trades", day=day, sample_rows=sample,
                           sample_cols=TRADE_COLS[:-1] + ["latency_ms"], latency_source="VENDOR")
            summary = "negative_latency: VENDOR events stamped as received before they happened"
        elif inc.incident_id == "INC-05":
            d = q[q["check_id"] == "price_band"].iloc[0]
            row = t[t["event_id"] == d["event_id"]].iloc[0]
            sample = pd.concat([t[t["event_id"] == d["event_id"]],
                                t[(t["instrument_key"] == row["instrument_key"]) & (t["source"] != "VENDOR")
                                  & (t["event_type"] == "trade")
                                  & ((t["ts_exchange"] - row["ts_exchange"]).abs() < pd.Timedelta(seconds=90))
                                  & (t["event_id"] != d["event_id"])].head(4)])
            world = _world(r, venue="PRIMARY", stream="trades", day=day, instrument=row["instrument_key"],
                           symbol=row["symbol"], at=row["ts_exchange"], sample_rows=sample, sample_cols=TRADE_COLS)
            summary = f"price_band fired on {row['symbol']} (PRIMARY)"
        elif inc.incident_id == "INC-06":
            d = q[q["check_id"] == "schema"]
            sample = d.head(5)[["event_id", "file", "raw_row", "symbol", "ts_exchange"]]
            world = _world(r, venue="ALT", stream="trades", day=day, sample_rows=sample,
                           sample_cols=["event_id", "file", "raw_row", "symbol", "ts_exchange"])
            summary = "schema: ALT trades partition does not conform to its contract"
        elif inc.incident_id == "INC-07":
            d = q[q["check_id"] == "crossed_book"]
            sample = r.quotes[r.quotes["event_id"].isin(d["event_id"])]
            world = _world(r, venue="ALT", stream="quotes", day=day, start=inc.started_at, end=d["ts_exchange"].max(),
                           sample_rows=sample, sample_cols=["event_id", "symbol", "ts_exchange", "ts_received", "bid", "ask"])
            summary = "crossed_book fired on ALT quotes"
        elif inc.incident_id == "INC-08":
            d = q[q["check_id"] == "symbol_known"]
            sample = t[t["event_id"].isin(d["event_id"])]
            world = _world(r, venue="PRIMARY", stream="trades", day=day, symbol=ref.SYMBOL_CHANGE["new"],
                           at=inc.detected_at, sample_rows=sample, sample_cols=TRADE_COLS)
            summary = f"symbol_known: events for {ref.SYMBOL_CHANGE['new']}, a symbol the master in force does not list"
        elif inc.incident_id == "CHK-01":
            conf = t[t["flags"].str.contains("band_confirmed", na=False)]
            row = conf.iloc[0]
            world = _world(r, venue="PRIMARY", stream="trades", day=day, instrument=row["instrument_key"],
                           symbol=row["symbol"], at=row["ts_exchange"], sample_rows=conf, sample_cols=TRADE_COLS)
            summary = f"price_band fired on {row['symbol']} (PRIMARY and ALT)"
        else:
            continue
        rows.append({
            "alert_id": f"ALR-{inc.incident_id.split('-')[1]}" if inc.incident_id.startswith("INC") else "ALR-C1",
            "incident_id": inc.incident_id, "check_id": inc.check_id, "venue": inc.venue, "stream": inc.stream,
            "day": day, "raised_at": inc.detected_at, "summary": summary,
            "world": json.dumps(world, default=str),
        })
    return pd.DataFrame(rows)

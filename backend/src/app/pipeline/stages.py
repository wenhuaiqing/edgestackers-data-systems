"""The pipeline: raw files in, governed events and bars out.

  land        read each raw file, hash it, record its schema
  contract    judge each partition against the contract version in force;
              a partition that breaks it is quarantined whole
  canonical   one trade shape for all three feeds (the vendor's is mapped)
  clock       measure the vendor's clock against PRIMARY and correct it,
              but only when the measurement is tight enough to trust
  symbols     resolve symbols to instruments through the dated master;
              hold what the master does not know yet
  dedupe      drop re-sent trades by (venue, trade id)
  arbitrate   fill PRIMARY's gaps from the vendor copy
  band        hold prints outside +/-8% of the five-minute median until an
              independent venue confirms them
  cancels     apply the exchange's cancels
  bars        one-minute bars as first published (point in time) and as
              finally known; the difference is the restatement log
  book        consolidated best bid and offer each minute
  gate        what the trading layer is allowed to do, per instrument-minute

Every control can be switched off. That is how the platform prices what each
one is worth (services/ablation.py) instead of asserting it.

Each day is independent of the others, so one day can be replayed from its
raw files alone and its partition hashes compared with the build's.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.app.pipeline import contracts as ct
from src.app.pipeline import reference as ref

CONTROLS: dict[str, str] = {
    "dedupe": "Drop re-sent trades by venue and trade id",
    "cancel_processing": "Apply the exchange's cancels and restate the bars they touched",
    "price_band": "Hold prints outside 8% of the five-minute median until another venue confirms",
    "clock_offset": "Measure the vendor's clock against PRIMARY and correct it before use",
    "feed_arbitration": "Fill PRIMARY's gaps from the vendor's copy of the feed",
    "crossed_book_filter": "Drop crossed quotes from the consolidated book",
    "symbol_master": "Key everything on instrument id through the dated symbol master",
    "quality_gate": "Block or downsize trading where a check is failing",
}
ALL_ON = {k: True for k in CONTROLS}

# Raw frames already read in this process, for ablation runs. A replay that
# exists to prove the raw files reproduce the output must not use it - see
# services/replay.py.
_RAW_CACHE: dict[str, tuple[pd.DataFrame, str, str]] = {}

BAND = 0.08
CONFIRM_SECONDS = 180
NEG_LATENCY_MS = 50


@dataclass
class Stage:
    name: str
    rows_in: int
    rows_out: int
    quarantined: int
    wall_ms: float
    cpu_ms: float
    note: str = ""


@dataclass
class PipelineResult:
    files: pd.DataFrame
    trades: pd.DataFrame
    quotes: pd.DataFrame
    quarantine: pd.DataFrame
    bars: pd.DataFrame
    book: pd.DataFrame
    restatements: pd.DataFrame
    clock_offsets: pd.DataFrame
    gate: pd.DataFrame
    partition_hashes: pd.DataFrame
    stages: list[Stage] = field(default_factory=list)


class _Timer:
    def __init__(self, stages: list[Stage]):
        self.stages = stages

    def __call__(self, name: str):
        timer = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.w = time.perf_counter()
                self_inner.c = time.process_time()
                self_inner.rows_in = 0
                self_inner.rows_out = 0
                self_inner.quarantined = 0
                self_inner.note = ""
                return self_inner

            def __exit__(self_inner, *exc):
                timer.stages.append(Stage(
                    name, self_inner.rows_in, self_inner.rows_out, self_inner.quarantined,
                    round((time.perf_counter() - self_inner.w) * 1000, 1),
                    round((time.process_time() - self_inner.c) * 1000, 1),
                    self_inner.note,
                ))
                return False

        return _Ctx()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _frame_hash(df: pd.DataFrame, cols: list[str]) -> str:
    """Stable digest of a partition's governed output."""
    view = df[cols].sort_values(cols[0], kind="mergesort").reset_index(drop=True)
    # Floats rounded first so the digest is about values, not representation.
    for c in view.columns:
        if view[c].dtype.kind == "f":
            view[c] = view[c].round(6)
    rows = pd.util.hash_pandas_object(view, index=False).to_numpy()
    return hashlib.sha256(rows.tobytes()).hexdigest()


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


QUARANTINE_COLS = ["event_id", "file", "raw_row", "venue", "stream", "day", "instrument_key", "symbol",
                   "check_id", "reason", "ts_exchange", "detected_at", "resolution", "resolved_at"]


def run_pipeline(raw_dir: Path, days: list[date] | None = None, controls: dict[str, bool] | None = None,
                 approved: dict[str, list[tuple[int, date]]] | None = None,
                 hash_files: bool = True, use_cache: bool = False) -> PipelineResult:
    raw_dir = Path(raw_dir)
    days = days or list(ref.TRADING_DAYS)
    on = {**ALL_ON, **(controls or {})}
    approved = approved or {}
    stages: list[Stage] = []
    timed = _Timer(stages)
    quarantine: list[pd.DataFrame] = []

    # ---- land ---------------------------------------------------------------
    with timed("land") as s:
        file_rows = []
        frames: dict[tuple[str, str, date], pd.DataFrame] = {}
        for day in days:
            stamp = day.isoformat()
            for venue, stream in [("PRIMARY", "trades"), ("PRIMARY", "quotes"), ("ALT", "trades"),
                                  ("ALT", "quotes"), ("VENDOR", "trades"), ("REF", "symbol_master")]:
                rel = f"{venue}/{stream}/{stamp}.parquet"
                path = raw_dir / rel
                cached = _RAW_CACHE.get(str(path)) if use_cache else None
                if cached is None:
                    table = pq.read_table(path)
                    frame = table.to_pandas()
                    frame["raw_row"] = np.arange(len(frame), dtype="int64")
                    frame["file"] = rel
                    cached = (frame, ", ".join(table.schema.names), sha256_file(path) if hash_files else "")
                    if use_cache:
                        _RAW_CACHE[str(path)] = cached
                frame, names, digest = cached
                frames[(venue, stream, day)] = frame.copy()
                file_rows.append({
                    "file": rel, "venue": venue, "stream": stream, "day": day, "rows": len(frame),
                    "sha256": digest, "fields": names,
                })
                s.rows_in += len(frame)
        files = pd.DataFrame(file_rows)
        s.rows_out = s.rows_in
        s.note = f"{len(files)} files"

    # ---- contract -----------------------------------------------------------
    with timed("contract") as s:
        verdicts = []
        for (venue, stream, day), frame in frames.items():
            cid = f"{venue.lower()}.{stream}"
            contract = ct.load_all()[cid]
            version = ct.active_version(cid, day, approved)
            cols = [c for c in frame.columns if c not in ("raw_row", "file")]
            v = ct.judge(contract, version, cols)
            verdicts.append({"file": f"{venue}/{stream}/{day.isoformat()}.parquet", "contract": cid,
                             "version": version, "ok": v.ok, "reason": v.reason})
            s.rows_in += len(frame)
            if not v.ok:
                q = pd.DataFrame({
                    "event_id": frame["event_id"] if "event_id" in frame else frame.get("vendor_seq").astype(str),
                    "file": frame["file"], "raw_row": frame["raw_row"], "venue": venue, "stream": stream,
                    "day": day, "instrument_key": None, "symbol": frame.get("symbol"),
                    "check_id": "schema", "reason": f"Partition breaks {cid} v{version}: {v.reason}",
                    "ts_exchange": frame.get("ts_exchange"), "detected_at": frame.get("ts_received"),
                    "resolution": "held until the contract is changed", "resolved_at": pd.NaT,
                })
                quarantine.append(q)
                s.quarantined += len(frame)
                frames[(venue, stream, day)] = frame.iloc[0:0]
            elif v.renamed:
                frames[(venue, stream, day)] = frame.rename(columns=v.renamed)
        contract_verdicts = pd.DataFrame(verdicts)
        files = files.merge(contract_verdicts, on="file", how="left")
        s.rows_out = s.rows_in - s.quarantined

    # ---- canonical ------------------------------------------------------------
    with timed("canonical") as s:
        canon_cols = ["event_id", "file", "raw_row", "venue", "source", "event_type", "symbol", "trade_id",
                      "ts_exchange", "ts_received", "price", "qty", "side", "cancels_trade_id"]
        trade_parts = []
        for (venue, stream, day), frame in frames.items():
            if stream != "trades" or frame.empty:
                continue
            if venue == "VENDOR":
                f = pd.DataFrame({
                    "event_id": "VS-" + frame["vendor_seq"].astype(str),
                    "file": frame["file"], "raw_row": frame["raw_row"],
                    "venue": "PRIMARY", "source": "VENDOR",
                    "event_type": frame["msg_type"].map({"T": "trade", "X": "trade_cancel"}),
                    "symbol": frame["ticker"], "trade_id": frame["src_trade_id"],
                    "ts_exchange": frame["exch_time"], "ts_received": frame["vendor_time"],
                    "price": frame["px"], "qty": frame["vol"], "side": frame["aggressor"],
                    "cancels_trade_id": frame["ref_trade_id"],
                })
            else:
                f = frame.copy()
                f["venue"] = venue
                f["source"] = venue
                f = f[canon_cols]
            f["day"] = day
            trade_parts.append(f)
        trades = pd.concat(trade_parts, ignore_index=True) if trade_parts else _empty(canon_cols + ["day"])
        trades["ts_exchange"] = pd.to_datetime(trades["ts_exchange"]).astype("datetime64[us]")
        trades["ts_received"] = pd.to_datetime(trades["ts_received"]).astype("datetime64[us]")
        trades["ts_exchange_raw"] = trades["ts_exchange"]
        trades["price"] = trades["price"].astype("float64")
        trades["qty"] = pd.to_numeric(trades["qty"]).astype("float64")
        trades["status"] = "accepted"
        trades["ts_available"] = trades["ts_received"]
        trades["ts_removed"] = pd.NaT
        trades["ts_removed"] = trades["ts_removed"].astype("datetime64[us]")
        trades["flags"] = ""
        trades["offset_ms"] = 0.0
        # When a check started holding the event; ts_available is when it let go.
        trades["held_from"] = pd.NaT
        trades["held_from"] = trades["held_from"].astype("datetime64[us]")

        quote_parts = []
        for (venue, stream, day), frame in frames.items():
            if stream != "quotes" or frame.empty:
                continue
            f = frame.copy()
            f["venue"] = venue
            f["day"] = day
            quote_parts.append(f)
        quote_cols = ["event_id", "symbol", "ts_exchange", "ts_received", "bid", "bid_size", "ask", "ask_size",
                      "raw_row", "file", "venue", "day"]
        quotes = pd.concat(quote_parts, ignore_index=True) if quote_parts else _empty(quote_cols)
        quotes["ts_exchange"] = pd.to_datetime(quotes["ts_exchange"]).astype("datetime64[us]")
        quotes["ts_received"] = pd.to_datetime(quotes["ts_received"]).astype("datetime64[us]")
        quotes["status"] = "accepted"
        s.rows_in = len(trades) + len(quotes)
        s.rows_out = s.rows_in
        s.note = f"{len(trades):,} trades, {len(quotes):,} quotes"

    # ---- clock ----------------------------------------------------------------
    with timed("clock") as s:
        offset_rows = []
        is_vendor = trades["source"] == "VENDOR"
        vendor_policy = ct.load_all()["vendor.trades"]["clock_offset"]["apply_when"]
        for day in days:
            vmask = is_vendor & (trades["day"] == day) & (trades["event_type"] == "trade")
            pmask = (trades["source"] == "PRIMARY") & (trades["day"] == day) & (trades["event_type"] == "trade")
            v = trades.loc[vmask, ["trade_id", "ts_exchange", "ts_received"]]
            p = trades.loc[pmask, ["trade_id", "ts_exchange"]].drop_duplicates("trade_id")
            m = v.merge(p, on="trade_id", suffixes=("_v", "_p")).sort_values("ts_received")
            diffs = (m["ts_exchange_v"] - m["ts_exchange_p"]).dt.total_seconds().to_numpy() * 1000.0
            first = diffs[: vendor_policy["min_matched"]]
            median = float(np.median(first)) if first.size else 0.0
            mad = float(np.median(np.abs(first - median))) if first.size else 0.0
            neg_before = int(((trades.loc[is_vendor & (trades["day"] == day), "ts_received"]
                               - trades.loc[is_vendor & (trades["day"] == day), "ts_exchange"])
                              .dt.total_seconds() * 1000 < -NEG_LATENCY_MS).sum())
            trusted = first.size >= vendor_policy["min_matched"] and mad <= vendor_policy["max_mad_ms"]
            apply = on["clock_offset"] and trusted and abs(median) > 5.0
            if apply:
                dmask = is_vendor & (trades["day"] == day)
                shift = pd.Timedelta(milliseconds=round(median))
                trades.loc[dmask, "ts_exchange"] = trades.loc[dmask, "ts_exchange"] - shift
                trades.loc[dmask, "offset_ms"] = float(round(median))
                trades.loc[dmask, "flags"] = trades.loc[dmask, "flags"] + "offset_corrected;"
            neg_after = int(((trades.loc[is_vendor & (trades["day"] == day), "ts_received"]
                              - trades.loc[is_vendor & (trades["day"] == day), "ts_exchange"])
                             .dt.total_seconds() * 1000 < -NEG_LATENCY_MS).sum())
            available_at = m["ts_received"].iloc[min(len(m), vendor_policy["min_matched"]) - 1] if len(m) else pd.NaT
            offset_rows.append({
                "day": day, "venue": "VENDOR", "matched": int(len(m)), "sample": int(first.size),
                "median_ms": round(median, 1), "mad_ms": round(mad, 2),
                "full_day_median_ms": round(float(np.median(diffs)), 1) if diffs.size else 0.0,
                "applied_ms": float(round(median)) if apply else 0.0, "trusted": bool(trusted),
                "negative_latency_before": neg_before, "negative_latency_after": neg_after,
                "estimated_at": available_at,
            })
        clock_offsets = pd.DataFrame(offset_rows)
        s.rows_in = int(is_vendor.sum())
        s.rows_out = s.rows_in
        s.note = "; ".join(f"{r['day']:%d/%m} {r['applied_ms']:+.0f} ms" for r in offset_rows if r["applied_ms"])

    # ---- symbols ----------------------------------------------------------------
    with timed("symbols") as s:
        masters = []
        for day in days:
            f = frames[("REF", "symbol_master", day)]
            sc = ref.SYMBOL_CHANGE
            arrived = sc["master_arrives"] if day == sc["effective"] else datetime.combine(day, datetime.min.time()) + timedelta(hours=6)
            g = f.copy()
            g["master_day"] = day
            g["arrived_at"] = np.datetime64(arrived, "us")
            masters.append(g)
        master = pd.concat(masters, ignore_index=True)
        # The master in force on each day: the snapshot for that day, or the
        # previous day's until today's arrives.
        known_from_rows = []
        for day in days:
            today = master[master["master_day"] == day]
            midnight = np.datetime64(datetime.combine(day, datetime.min.time()), "us")
            for _, row in today.iterrows():
                valid_from = pd.Timestamp(row["valid_from"]).date()
                valid_to = None if pd.isna(row["valid_to"]) else pd.Timestamp(row["valid_to"]).date()
                if valid_from <= day and (valid_to is None or valid_to >= day):
                    # A symbol already valid yesterday was known before today's
                    # file landed; a new one only from the moment it did.
                    known_from = midnight if valid_from < day else row["arrived_at"]
                    known_from_rows.append({"day": day, "symbol": row["symbol"],
                                            "instrument_id": row["instrument_id"], "known_from": known_from})
        known = pd.DataFrame(known_from_rows)
        trades = trades.merge(known, on=["day", "symbol"], how="left")
        quotes = quotes.merge(known, on=["day", "symbol"], how="left")
        if on["symbol_master"]:
            for frame in (trades, quotes):
                frame["instrument_key"] = frame["instrument_id"]
            held_t = trades["known_from"].notna() & (trades["ts_received"] < trades["known_from"])
            held_q = quotes["known_from"].notna() & (quotes["ts_received"] < quotes["known_from"])
            trades.loc[held_t, "held_from"] = trades.loc[held_t, "ts_received"]
            trades.loc[held_t, "ts_available"] = trades.loc[held_t, "known_from"]
            trades.loc[held_t, "flags"] = trades.loc[held_t, "flags"] + "held_unknown_symbol;"
            quotes["ts_available"] = quotes["ts_received"]
            quotes.loc[held_q, "ts_available"] = quotes.loc[held_q, "known_from"]
            held = trades[held_t]
            if len(held):
                quarantine.append(pd.DataFrame({
                    "event_id": held["event_id"], "file": held["file"], "raw_row": held["raw_row"],
                    "venue": held["source"], "stream": "trades", "day": held["day"],
                    "instrument_key": held["instrument_id"], "symbol": held["symbol"],
                    "check_id": "symbol_known",
                    "reason": "Symbol not in the symbol master in force when the event arrived",
                    "ts_exchange": held["ts_exchange"], "detected_at": held["ts_received"],
                    "resolution": "released when the symbol master arrived", "resolved_at": held["known_from"],
                }))
            s.quarantined = int(held_t.sum() + held_q.sum())
        else:
            for frame in (trades, quotes):
                frame["instrument_key"] = frame["symbol"]
            quotes["ts_available"] = quotes["ts_received"]
        s.rows_in = len(trades) + len(quotes)
        s.rows_out = s.rows_in
        s.note = f"{s.quarantined:,} held for a late master" if s.quarantined else ""

    # ---- dedupe -----------------------------------------------------------------
    with timed("dedupe") as s:
        direct = trades["source"].isin(["PRIMARY", "ALT"]) & (trades["event_type"] == "trade")
        s.rows_in = int(direct.sum())
        if on["dedupe"]:
            order = trades.sort_values(["ts_received", "event_id"], kind="mergesort")
            dup_index = order[direct.loc[order.index]].duplicated(["source", "trade_id"], keep="first")
            dup_index = dup_index[dup_index].index
            trades.loc[dup_index, "status"] = "duplicate"
            dups = trades.loc[dup_index]
            if len(dups):
                first_seen = (order[direct.loc[order.index]].drop_duplicates(["source", "trade_id"])
                              .set_index(["source", "trade_id"])["event_id"])
                quarantine.append(pd.DataFrame({
                    "event_id": dups["event_id"], "file": dups["file"], "raw_row": dups["raw_row"],
                    "venue": dups["source"], "stream": "trades", "day": dups["day"],
                    "instrument_key": dups["instrument_key"], "symbol": dups["symbol"],
                    "check_id": "duplicate_trade_id",
                    "reason": "Trade id already received as " + pd.Series(
                        [first_seen.get((a, b), "?") for a, b in zip(dups["source"], dups["trade_id"])],
                        index=dups.index),
                    "ts_exchange": dups["ts_exchange"], "detected_at": dups["ts_received"],
                    "resolution": "dropped; the first copy is kept", "resolved_at": dups["ts_received"],
                }))
            s.quarantined = len(dups)
        s.rows_out = s.rows_in - s.quarantined

    # ---- arbitrate ------------------------------------------------------------------
    with timed("arbitrate") as s:
        is_vendor = trades["source"] == "VENDOR"
        s.rows_in = int(is_vendor.sum())
        direct_ids = set(trades.loc[trades["source"] == "PRIMARY", "trade_id"].dropna())
        direct_cancels = set(trades.loc[(trades["source"] == "PRIMARY") & (trades["event_type"] == "trade_cancel"),
                                        "cancels_trade_id"].dropna())
        if on["feed_arbitration"]:
            fills_trade = is_vendor & (trades["event_type"] == "trade") & ~trades["trade_id"].isin(direct_ids)
            fills_cancel = is_vendor & (trades["event_type"] == "trade_cancel") & ~trades["cancels_trade_id"].isin(direct_cancels)
            used = fills_trade | fills_cancel
        else:
            used = pd.Series(False, index=trades.index)
        trades.loc[is_vendor & ~used, "status"] = "redundant"
        trades.loc[used, "flags"] = trades.loc[used, "flags"] + "gap_fill;"
        s.rows_out = int(used.sum())
        s.note = f"{int(used.sum()):,} gap fills from the vendor feed"

    # ---- band ---------------------------------------------------------------------------
    with timed("band") as s:
        live = (trades["status"] == "accepted") & (trades["event_type"] == "trade")
        t = trades.loc[live, ["instrument_key", "ts_exchange", "price", "venue", "ts_received", "ts_available"]].copy()
        t["minute"] = t["ts_exchange"].dt.floor("min")
        s.rows_in = len(t)
        if on["price_band"] and len(t):
            med = t.groupby(["instrument_key", "minute"])["price"].median().rename("minute_median").reset_index()
            refs = []
            for key, g in med.groupby("instrument_key", sort=False):
                g = g.sort_values("minute").set_index("minute")
                r = g["minute_median"].rolling("5min", closed="left").median()
                r = r.fillna(g["minute_median"])
                refs.append(pd.DataFrame({"instrument_key": key, "minute": r.index, "ref_price": r.to_numpy()}))
            ref_df = pd.concat(refs, ignore_index=True)
            t = t.merge(ref_df, on=["instrument_key", "minute"], how="left")
            t.index = trades.index[live]
            dev = t["price"] / t["ref_price"] - 1.0
            flagged = dev.abs() > BAND
            fl = t[flagged].copy()
            fl["dev"] = dev[flagged]
            held_ids, released = [], {}
            for idx, row in fl.iterrows():
                lo = row["ts_exchange"] - pd.Timedelta(seconds=CONFIRM_SECONDS)
                hi = row["ts_exchange"] + pd.Timedelta(seconds=CONFIRM_SECONDS)
                others = fl[(fl["instrument_key"] == row["instrument_key"]) & (fl["venue"] != row["venue"])
                            & (fl["ts_exchange"] >= lo) & (fl["ts_exchange"] <= hi)
                            & (np.sign(fl["dev"]) == np.sign(row["dev"]))]
                if len(others):
                    released[idx] = max(row["ts_available"], others["ts_available"].min())
                else:
                    held_ids.append(idx)
            for idx, when in released.items():
                trades.at[idx, "held_from"] = trades.at[idx, "ts_received"]
                trades.at[idx, "ts_available"] = when
                trades.at[idx, "flags"] = trades.at[idx, "flags"] + "band_confirmed;"
            if held_ids:
                trades.loc[held_ids, "status"] = "held"
                trades.loc[held_ids, "held_from"] = trades.loc[held_ids, "ts_received"]
                trades.loc[held_ids, "ts_available"] = pd.NaT
                h = trades.loc[held_ids]
                quarantine.append(pd.DataFrame({
                    "event_id": h["event_id"], "file": h["file"], "raw_row": h["raw_row"],
                    "venue": h["source"], "stream": "trades", "day": h["day"],
                    "instrument_key": h["instrument_key"], "symbol": h["symbol"], "check_id": "price_band",
                    "reason": [f"Price {p:.2f} is {d:+.0%} from the five-minute median {r:.2f}; no other venue confirms"
                               for p, d, r in zip(h["price"], fl.loc[held_ids, "dev"], fl.loc[held_ids, "ref_price"])],
                    "ts_exchange": h["ts_exchange"], "detected_at": h["ts_received"],
                    "resolution": "held pending confirmation", "resolved_at": pd.NaT,
                }))
            s.quarantined = len(held_ids)
            s.note = f"{len(fl)} outside the band; {len(released)} confirmed by another venue, {len(held_ids)} held"
        s.rows_out = s.rows_in - s.quarantined

    # ---- cancels --------------------------------------------------------------------------
    with timed("cancels") as s:
        cancel_rows = trades[(trades["event_type"] == "trade_cancel") & (trades["status"] == "accepted")]
        s.rows_in = len(cancel_rows)
        if on["cancel_processing"]:
            for _, c in cancel_rows.iterrows():
                target = trades.index[(trades["trade_id"] == c["cancels_trade_id"]) & (trades["event_type"] == "trade")
                                      & trades["status"].isin(["accepted", "held"])]
                for idx in target:
                    was_held = trades.at[idx, "status"] == "held"
                    trades.at[idx, "ts_removed"] = c["ts_received"]
                    trades.at[idx, "status"] = "cancelled"
                    trades.at[idx, "flags"] = trades.at[idx, "flags"] + ("cancel_while_held;" if was_held else "cancelled_after_use;")
                s.rows_out += len(target)
            # Resolve the quarantine entry for a held print once the exchange cancels it.
            for q in quarantine:
                if len(q) and (q["check_id"] == "price_band").any():
                    ids = trades.loc[trades["status"] == "cancelled", "event_id"]
                    hit = q["event_id"].isin(ids) & (q["check_id"] == "price_band")
                    if hit.any():
                        removed = trades.set_index("event_id").loc[q.loc[hit, "event_id"], "ts_removed"].to_numpy()
                        q.loc[hit, "resolution"] = "cancelled by the exchange"
                        q.loc[hit, "resolved_at"] = removed
        s.note = f"{s.rows_out} trades cancelled" if on["cancel_processing"] else "cancels ignored"

    # ---- bars -------------------------------------------------------------------------------
    con = duckdb.connect()
    with timed("bars") as s:
        usable = trades[(trades["event_type"] == "trade") & trades["status"].isin(["accepted", "cancelled"])].copy()
        usable["minute"] = usable["ts_exchange"].dt.floor("min")
        usable["publish_at"] = usable["minute"] + pd.Timedelta(seconds=60 + ref.WATERMARK_SECONDS)
        usable["in_published"] = (usable["ts_available"] <= usable["publish_at"]) & (
            usable["ts_removed"].isna() | (usable["ts_removed"] > usable["publish_at"]))
        usable["in_final"] = usable["ts_removed"].isna()
        con.register("usable", usable[["instrument_key", "minute", "venue", "source", "ts_exchange", "price", "qty",
                                       "in_published", "in_final", "flags", "ts_available", "publish_at",
                                       "ts_removed"]])
        bars = con.execute("""
            WITH b AS (
              SELECT instrument_key, minute,
                     count(*) FILTER (WHERE in_published) AS pub_trades,
                     sum(qty) FILTER (WHERE in_published) AS pub_volume,
                     arg_min(price, ts_exchange) FILTER (WHERE in_published) AS pub_open,
                     max(price) FILTER (WHERE in_published) AS pub_high,
                     min(price) FILTER (WHERE in_published) AS pub_low,
                     arg_max(price, ts_exchange) FILTER (WHERE in_published) AS pub_close,
                     sum(price * qty) FILTER (WHERE in_published) / nullif(sum(qty) FILTER (WHERE in_published), 0) AS pub_vwap,
                     count(*) FILTER (WHERE in_final) AS trades,
                     sum(qty) FILTER (WHERE in_final) AS volume,
                     arg_min(price, ts_exchange) FILTER (WHERE in_final) AS open,
                     max(price) FILTER (WHERE in_final) AS high,
                     min(price) FILTER (WHERE in_final) AS low,
                     arg_max(price, ts_exchange) FILTER (WHERE in_final) AS close,
                     sum(price * qty) FILTER (WHERE in_final) / nullif(sum(qty) FILTER (WHERE in_final), 0) AS vwap,
                     count(DISTINCT venue) FILTER (WHERE in_final) AS venues,
                     sum(qty) FILTER (WHERE in_final AND venue = 'ALT') AS alt_volume,
                     count(*) FILTER (WHERE in_final AND source = 'VENDOR') AS gap_fill_trades
              FROM usable GROUP BY 1, 2
            )
            SELECT * FROM b ORDER BY instrument_key, minute
        """).df()
        bars["day"] = bars["minute"].dt.date
        bars["restated"] = (bars["pub_trades"].fillna(0) != bars["trades"].fillna(0)) | (
            (bars["pub_vwap"] - bars["vwap"]).abs().fillna(1) > 1e-9)
        restated_events = con.execute("""
            SELECT instrument_key, minute,
                   string_agg(DISTINCT CASE
                     WHEN in_published AND NOT in_final THEN 'cancelled after publication'
                     WHEN NOT in_published AND in_final AND flags LIKE '%band_confirmed%' THEN 'held by the price band, then confirmed'
                     WHEN NOT in_published AND in_final AND flags LIKE '%held_unknown_symbol%' THEN 'held for a late symbol master'
                     WHEN NOT in_published AND in_final AND source = 'VENDOR' THEN 'vendor gap fill after the watermark'
                     WHEN NOT in_published AND in_final THEN 'arrived after the watermark'
                   END, '; ') AS cause,
                   count(*) FILTER (WHERE in_published <> in_final) AS events_changed
            FROM usable
            WHERE in_published <> in_final
            GROUP BY 1, 2
        """).df()
        restatements = bars[bars["restated"]][["instrument_key", "minute", "pub_trades", "trades", "pub_volume",
                                               "volume", "pub_close", "close", "pub_vwap", "vwap"]]
        restatements = restatements.merge(restated_events, on=["instrument_key", "minute"], how="left")
        s.rows_in = len(usable)
        s.rows_out = len(bars)
        s.note = f"{len(bars):,} bars, {len(restatements):,} restated"

    # ---- book ---------------------------------------------------------------------------------
    with timed("book") as s:
        qv = quotes.copy()
        qv["crossed"] = qv["bid"] >= qv["ask"]
        if on["crossed_book_filter"]:
            qv.loc[qv["crossed"], "status"] = "crossed"
            crossed = qv[qv["crossed"]]
            if len(crossed):
                quarantine.append(pd.DataFrame({
                    "event_id": crossed["event_id"], "file": crossed["file"], "raw_row": crossed["raw_row"],
                    "venue": crossed["venue"], "stream": "quotes", "day": crossed["day"],
                    "instrument_key": crossed["instrument_key"], "symbol": crossed["symbol"],
                    "check_id": "crossed_book",
                    "reason": [f"Bid {b:.3f} at or above ask {a:.3f}" for b, a in zip(crossed["bid"], crossed["ask"])],
                    "ts_exchange": crossed["ts_exchange"], "detected_at": crossed["ts_received"],
                    "resolution": "excluded from the consolidated book", "resolved_at": crossed["ts_received"],
                }))
            s.quarantined = len(crossed)
        qv["minute"] = qv["ts_exchange"].dt.floor("min")
        qv["publish_at"] = qv["minute"] + pd.Timedelta(seconds=60 + ref.WATERMARK_SECONDS)
        good = qv[(qv["status"] == "accepted") & (qv["ts_available"] <= qv["publish_at"])]
        con.register("good_quotes", good[["instrument_key", "venue", "minute", "ts_exchange", "bid", "ask", "crossed"]])
        con.register("all_quotes", qv[["instrument_key", "venue", "minute", "crossed"]])
        book = con.execute("""
            WITH last_q AS (
              SELECT instrument_key, venue, minute,
                     arg_max(bid, ts_exchange) AS bid, arg_max(ask, ts_exchange) AS ask
              FROM good_quotes GROUP BY 1, 2, 3
            ), seen_crossed AS (
              SELECT instrument_key, minute, bool_or(crossed) AS crossed_seen FROM all_quotes GROUP BY 1, 2
            )
            SELECT l.instrument_key, l.minute,
                   max(bid) AS best_bid, min(ask) AS best_ask,
                   count(*) AS venues_quoting,
                   max(bid) >= min(ask) AS crossed,
                   coalesce(any_value(c.crossed_seen), false) AS crossed_seen
            FROM last_q l LEFT JOIN seen_crossed c USING (instrument_key, minute)
            GROUP BY 1, 2 ORDER BY 1, 2
        """).df()
        quotes = qv
        s.rows_in = len(qv)
        s.rows_out = len(book)

    # ---- gate ------------------------------------------------------------------------------------
    with timed("gate") as s:
        gate = bars[["instrument_key", "minute", "day"]].copy()
        gate["state"] = "open"
        gate["reason"] = ""
        if on["quality_gate"]:
            # Every minute an event for the instrument was being held by a check.
            held = trades[trades["held_from"].notna() & trades["status"].isin(["accepted", "held", "cancelled"])]
            day_end = pd.to_datetime(held["day"].astype(str) + " 16:00:00")
            until = held["ts_available"].fillna(held["ts_removed"]).fillna(day_end)
            blocked_keys = set()
            for k, a, b in zip(held["instrument_key"], held["held_from"].dt.floor("min"), until.dt.floor("min")):
                for m in pd.date_range(a, b, freq="min"):
                    blocked_keys.add((k, m))
            blocked = pd.Series([(k, m) in blocked_keys for k, m in zip(gate["instrument_key"], gate["minute"])],
                                index=gate.index, dtype=bool)
            gate.loc[blocked, ["state", "reason"]] = ["blocked", "a print or symbol is held by a check"]
            schema_days = {(v, d) for q in quarantine if len(q)
                           for v, d, c in zip(q["venue"], q["day"], q["check_id"]) if c == "schema"}
            alt_missing = gate["day"].map(lambda d: ("ALT", d) in schema_days).astype(bool).to_numpy()
            g2 = gate.merge(book[["instrument_key", "minute", "crossed_seen"]], on=["instrument_key", "minute"], how="left")
            g2 = g2.merge(bars[["instrument_key", "minute", "gap_fill_trades"]], on=["instrument_key", "minute"], how="left")
            crossed_seen = g2["crossed_seen"].fillna(False).astype(bool).to_numpy()
            on_backup = (g2["gap_fill_trades"].fillna(0) > 0).to_numpy()
            degrade = (gate["state"] == "open").to_numpy() & (alt_missing | crossed_seen | on_backup)
            reasons = np.where(alt_missing, "ALT quarantined: consolidated volume incomplete",
                               np.where(crossed_seen, "a venue's book was crossed", "PRIMARY on the vendor backup"))
            gate.loc[degrade, "state"] = "degraded"
            gate.loc[degrade, "reason"] = reasons[degrade]
        s.rows_in = len(gate)
        s.rows_out = int((gate["state"] == "open").sum())
        s.note = f"{int((gate['state'] == 'blocked').sum()):,} blocked, {int((gate['state'] == 'degraded').sum()):,} degraded"
    con.close()

    q_all = pd.concat([q for q in quarantine if len(q)], ignore_index=True) if any(len(q) for q in quarantine) \
        else _empty(QUARANTINE_COLS)
    # A vendor copy that was never needed is not a quarantined event.
    redundant = set(trades.loc[trades["status"] == "redundant", "event_id"])
    q_all = q_all[~q_all["event_id"].isin(redundant)].reset_index(drop=True)

    # ---- partition hashes: the replay contract ---------------------------------------------------
    hashes = []
    tcols = ["event_id", "status", "instrument_key", "ts_exchange", "ts_available", "price", "qty"]
    for (src, day), g in trades.groupby(["source", "day"]):
        hashes.append({"partition": f"{src}/trades/{day.isoformat()}", "rows": len(g), "sha256": _frame_hash(g, tcols)})
    qcols = ["event_id", "status", "instrument_key", "ts_exchange", "bid", "ask"]
    for (venue, day), g in quotes.groupby(["venue", "day"]):
        hashes.append({"partition": f"{venue}/quotes/{day.isoformat()}", "rows": len(g), "sha256": _frame_hash(g, qcols)})
    bcols = ["instrument_key", "minute", "pub_trades", "pub_volume", "pub_close", "pub_vwap",
             "trades", "volume", "close", "vwap"]
    for day, g in bars.assign(_k=bars["instrument_key"] + bars["minute"].astype(str)).groupby("day"):
        hashes.append({"partition": f"BARS/1m/{day.isoformat()}", "rows": len(g),
                       "sha256": _frame_hash(g, ["_k"] + bcols)})

    return PipelineResult(files=files, trades=trades, quotes=quotes, quarantine=q_all, bars=bars, book=book,
                          restatements=restatements, clock_offsets=clock_offsets, gate=gate,
                          partition_hashes=pd.DataFrame(hashes), stages=stages)


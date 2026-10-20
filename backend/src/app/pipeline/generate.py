"""Deterministic synthetic market feeds, with the defects real feeds have.

Three feeds over five sessions:

  PRIMARY  direct feed of the primary exchange - trades and top-of-book quotes
  ALT      direct feed of an alternative venue - trades and quotes
  VENDOR   a vendor's redundant copy of PRIMARY's trades, in the vendor's own
           shape (different field names, its own sequence, ~180 ms later)

plus a daily symbol master. Prices follow a slow random walk with a
mean-reverting component on top, which is what gives a short-horizon
mean-reversion strategy something to find - and what a dirty print
destroys first.

Same seed, same bytes: the build hashes the output and the image refuses to
start on a mismatch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.app.pipeline import reference as ref

US = 1_000_000  # microseconds per second


@dataclass
class RawFile:
    path: str             # relative to data/raw
    venue: str
    stream: str
    day: date
    rows: int
    arrived_at: datetime


def _session_start(day: date) -> np.datetime64:
    return np.datetime64(datetime.combine(day, ref.SESSION_OPEN), "us")


def _to_ts(day: date, seconds: np.ndarray) -> np.ndarray:
    return _session_start(day) + (seconds * US).astype("int64").astype("timedelta64[us]")


def _round_tick(values: np.ndarray, tick: float, how: str) -> np.ndarray:
    scaled = values / tick
    if how == "down":
        scaled = np.floor(scaled + 1e-9)
    elif how == "up":
        scaled = np.ceil(scaled - 1e-9)
    else:
        scaled = np.round(scaled)
    return np.round(scaled * tick, 4)


def _fair_path(rng: np.random.Generator, inst: ref.Instrument, open_price: float,
               day: date) -> np.ndarray:
    """Fair value at one-second resolution for one session."""
    n = ref.SESSION_SECONDS + 1
    sigma = 0.6 * inst.daily_vol / math.sqrt(ref.SESSION_SECONDS)
    walk = np.cumsum(rng.normal(0.0, sigma, n))
    walk -= walk[0]
    # Mean-reverting component, half-life ten minutes, stationary sd 0.45%:
    # the inefficiency a short-horizon strategy can find, and the first thing
    # a dirty print hides.
    phi = math.exp(-math.log(2) / (10 * 60))
    sd = 0.0045
    shocks = rng.normal(0.0, sd * math.sqrt(1 - phi * phi), n)
    ou = np.empty(n)
    ou[0] = 0.0
    for i in range(1, n):
        ou[i] = phi * ou[i - 1] + shocks[i]
    log_path = walk + ou
    gm = ref.GENUINE_MOVE
    if day == gm["day"] and inst.symbol == gm["symbol"]:
        at_s = int((gm["at"] - datetime.combine(day, ref.SESSION_OPEN)).total_seconds())
        log_path[at_s:] += math.log(1 + gm["jump"])
    return open_price * np.exp(log_path)


def _half_spread(price: np.ndarray, tick: float) -> np.ndarray:
    return np.maximum(tick, np.round(price * 0.0003 / tick) * tick)


def _latency_seconds(rng: np.random.Generator, n: int, venue: str) -> np.ndarray:
    median = ref.VENUES[venue].median_latency_ms / 1000.0
    lat = median * np.exp(rng.normal(0.0, 0.5, n))
    late = rng.random(n) < ref.LATE_SHARE[venue]
    if venue == "VENDOR":
        lat[late] += rng.uniform(0.5, 6.0, late.sum())
    else:
        lat[late] += rng.uniform(3.5, 9.0, late.sum())
    return lat


def _trades(rng: np.random.Generator, fair: np.ndarray, tick: float, rate: float,
            day: date, symbol: str) -> pd.DataFrame:
    n = rng.poisson(rate * ref.SESSION_SECONDS)
    t = np.sort(rng.uniform(0.0, ref.SESSION_SECONDS, n))
    f = fair[t.astype(int)]
    hs = _half_spread(f, tick)
    buy = rng.random(n) < 0.5
    price = np.where(buy, _round_tick(f + hs, tick, "up"), _round_tick(f - hs, tick, "down"))
    qty = np.clip(np.round(np.exp(rng.normal(math.log(800), 1.0, n))), 1, 50_000).astype("int64")
    return pd.DataFrame({
        "symbol": symbol,
        "t": t,
        "ts_exchange": _to_ts(day, t),
        "price": price,
        "qty": qty,
        "side": np.where(buy, "B", "S"),
    })


def _quotes(rng: np.random.Generator, fair: np.ndarray, tick: float, day: date,
            symbol: str) -> pd.DataFrame:
    base = np.arange(0.0, ref.SESSION_SECONDS, 10.0)
    t = np.sort(base + rng.uniform(0.0, 2.0, base.size))
    f = fair[t.astype(int)]
    hs = _half_spread(f, tick)
    bid = _round_tick(f - hs, tick, "down")
    width = np.maximum(1, np.round(2 * hs / tick)) * tick
    ask = np.round(bid + width, 4)
    return pd.DataFrame({
        "symbol": symbol,
        "t": t,
        "ts_exchange": _to_ts(day, t),
        "bid": bid,
        "bid_size": (rng.integers(1, 40, t.size) * 100).astype("int64"),
        "ask": ask,
        "ask_size": (rng.integers(1, 40, t.size) * 100).astype("int64"),
    })


def _symbol_on(inst: ref.Instrument, day: date) -> str:
    sc = ref.SYMBOL_CHANGE
    if inst.instrument_id == sc["instrument_id"] and day >= sc["effective"]:
        return sc["new"]
    return inst.symbol


def _with_received(df: pd.DataFrame, rng: np.random.Generator, venue: str) -> pd.DataFrame:
    lat = _latency_seconds(rng, len(df), venue)
    df["ts_received"] = df["ts_exchange"] + (lat * US).astype("int64").astype("timedelta64[us]")
    return df


def _assign_ids(df: pd.DataFrame, prefix: str, day: date) -> pd.DataFrame:
    """Feed sequence: event ids follow arrival order, as on the wire."""
    df = df.sort_values(["ts_received", "ts_exchange"], kind="mergesort").reset_index(drop=True)
    stamp = day.strftime("%Y%m%d")
    df.insert(0, "event_id", [f"{prefix}-{stamp}-{i + 1:07d}" for i in range(len(df))])
    return df


def _in_gap(ts: pd.Series, venue: str, day: date) -> np.ndarray:
    mask = np.zeros(len(ts), dtype=bool)
    for gap in ref.FEED_GAPS:
        if gap["venue"] == venue and gap["day"] == day:
            mask |= ((ts >= np.datetime64(gap["start"], "us")) & (ts < np.datetime64(gap["end"], "us"))).to_numpy()
    return mask


def generate(out_dir: Path, bad_print_at: datetime | None = None,
             bad_print_multiplier: float | None = None) -> list[RawFile]:
    """Write every raw file under out_dir and return the manifest."""
    out_dir = Path(out_dir)
    files: list[RawFile] = []
    bp = ref.BAD_PRINT
    bad_at = bad_print_at or bp["default_at"]
    multiplier = bad_print_multiplier or bp["multiplier"]

    closes = {i.instrument_id: i.base_price for i in ref.INSTRUMENTS}

    for d_idx, day in enumerate(ref.TRADING_DAYS):
        prim_trades, alt_trades, prim_quotes, alt_quotes = [], [], [], []
        for i_idx, inst in enumerate(ref.INSTRUMENTS):
            rng = np.random.default_rng([ref.SEED, d_idx, i_idx])
            tick = ref.tick_size(inst.base_price)
            fair = _fair_path(rng, inst, closes[inst.instrument_id], day)
            closes[inst.instrument_id] = float(fair[-1])
            symbol = _symbol_on(inst, day)

            pt = _trades(rng, fair, tick, inst.primary_rate, day, symbol)
            at_ = _trades(rng, fair, tick, inst.primary_rate * inst.alt_share, day, symbol)
            pq = _quotes(rng, fair, tick, day, symbol)
            aq = _quotes(rng, fair, tick, day, symbol)

            if day == bp["day"] and inst.symbol == bp["symbol"]:
                s = (bad_at - datetime.combine(day, ref.SESSION_OPEN)).total_seconds()
                normal = float(fair[int(s)])
                pt = pd.concat([pt, pd.DataFrame({
                    "symbol": [symbol], "t": [s], "ts_exchange": [np.datetime64(bad_at, "us")],
                    "price": [round(normal * multiplier, 2 if multiplier >= 1 else 3)], "qty": [bp["qty"]],
                    "side": ["B" if multiplier >= 1 else "S"],
                })], ignore_index=True)

            prim_trades.append(pt)
            alt_trades.append(at_)
            prim_quotes.append(pq)
            alt_quotes.append(aq)

        rng = np.random.default_rng([ref.SEED, d_idx, 999])

        # ---- PRIMARY trades, full (before the gaps take anything) ----------
        pt = pd.concat(prim_trades, ignore_index=True).sort_values(["ts_exchange", "symbol"], kind="mergesort")
        pt = pt.reset_index(drop=True)
        pt["trade_id"] = [f"P{d_idx + 1}{i + 1:07d}" for i in range(len(pt))]
        pt["event_type"] = "trade"
        pt["cancels_trade_id"] = None
        if day == bp["day"]:
            bad_row = pt[(pt["ts_exchange"] == np.datetime64(bad_at, "us")) & (pt["qty"] == bp["qty"])]
            bad_id = bad_row["trade_id"].iloc[0]
            cancel_ts = np.datetime64(bad_at + timedelta(seconds=bp["cancel_after_seconds"]), "us")
            pt = pd.concat([pt, pd.DataFrame({
                "symbol": [bad_row["symbol"].iloc[0]], "t": [0.0], "ts_exchange": [cancel_ts],
                "price": [np.nan], "qty": [pd.NA], "side": [None],
                "trade_id": [f"P{d_idx + 1}X000001"], "event_type": ["trade_cancel"],
                "cancels_trade_id": [bad_id],
            })], ignore_index=True)
        pt = _with_received(pt, rng, "PRIMARY")

        # ---- VENDOR: a copy of PRIMARY in its own shape --------------------
        vd = pt.copy()
        vendor_lat = _latency_seconds(rng, len(vd), "VENDOR")
        vd["vendor_time"] = vd["ts_exchange"] + (vendor_lat * US).astype("int64").astype("timedelta64[us]")
        skew = ref.VENDOR_SKEW
        exch = vd["ts_exchange"].copy()
        skewed = exch >= np.datetime64(skew["from"], "us")
        exch[skewed] = exch[skewed] + np.timedelta64(int(skew["offset_ms"] * 1000), "us")
        vd["exch_time"] = exch
        vd = vd.sort_values(["vendor_time", "ts_exchange"], kind="mergesort").reset_index(drop=True)
        vendor = pd.DataFrame({
            "vendor_seq": np.arange(1, len(vd) + 1, dtype="int64") + (d_idx + 1) * 10_000_000,
            "msg_type": np.where(vd["event_type"] == "trade", "T", "X"),
            "src_venue": "XPRI",
            "ticker": vd["symbol"],
            "src_trade_id": np.where(vd["event_type"] == "trade", vd["trade_id"], None),
            "exch_time": vd["exch_time"],
            "vendor_time": vd["vendor_time"],
            "px": vd["price"],
            "vol": vd["qty"].astype("Int64"),
            "aggressor": vd["side"],
            "ref_trade_id": vd["cancels_trade_id"],
        })

        # ---- PRIMARY as delivered: gaps removed ---------------------------
        pt = pt[~_in_gap(pt["ts_exchange"], "PRIMARY", day)]
        pt = _assign_ids(pt, "PE", day)
        primary_trades = pt[["event_id", "event_type", "symbol", "trade_id", "ts_exchange", "ts_received",
                             "price", "qty", "side", "cancels_trade_id"]].copy()
        primary_trades["qty"] = primary_trades["qty"].astype("Int64")

        # ---- ALT trades: duplicates, then drift ---------------------------
        at_ = pd.concat(alt_trades, ignore_index=True).sort_values(["ts_exchange", "symbol"], kind="mergesort")
        at_ = at_.reset_index(drop=True)
        at_["trade_id"] = [f"A{d_idx + 1}{i + 1:07d}" for i in range(len(at_))]
        at_["event_type"] = "trade"
        at_["cancels_trade_id"] = None
        at_ = _with_received(at_, rng, "ALT")
        db = ref.DUP_BURST
        if day == db["day"]:
            window = at_[(at_["ts_exchange"] >= np.datetime64(db["resend_from"], "us"))
                         & (at_["ts_exchange"] < np.datetime64(db["resend_to"], "us"))].copy()
            base = np.datetime64(db["reconnect_at"], "us")
            window["ts_received"] = base + (np.arange(len(window)) * 2000).astype("timedelta64[us]")
            at_ = pd.concat([at_, window], ignore_index=True)
        at_ = _assign_ids(at_, "AE", day)
        alt_cols = ["event_id", "event_type", "symbol", "trade_id", "ts_exchange", "ts_received",
                    "price", "qty", "side", "cancels_trade_id"]
        alt_trades_df = at_[alt_cols].copy()
        alt_trades_df["qty"] = alt_trades_df["qty"].astype("Int64")
        sd = ref.SCHEMA_DRIFT
        if day >= sd["from_day"]:
            alt_trades_df = alt_trades_df.rename(columns=sd["renamed"])
            alt_trades_df["liquidity_flag"] = np.where(rng.random(len(alt_trades_df)) < 0.55, "A", "R")

        # ---- Quotes --------------------------------------------------------
        pq = pd.concat(prim_quotes, ignore_index=True)
        pq = pq[~_in_gap(pq["ts_exchange"], "PRIMARY", day)]
        pq = _assign_ids(_with_received(pq, rng, "PRIMARY"), "PQ", day)
        aq = pd.concat(alt_quotes, ignore_index=True)
        cb = ref.CROSSED_BOOK
        if day == cb["day"]:
            sym_on_day = {_symbol_on(i, day) for i in ref.INSTRUMENTS if i.symbol in cb["symbols"]}
            mask = (aq["symbol"].isin(sym_on_day)
                    & (aq["ts_exchange"] >= np.datetime64(cb["start"], "us"))
                    & (aq["ts_exchange"] < np.datetime64(cb["end"], "us"))).to_numpy()
            ticks = np.array([ref.tick_size(ref.INSTRUMENT_BY_SYMBOL[s].base_price) for s in aq.loc[mask, "symbol"]])
            aq.loc[mask, "ask"] = np.round(aq.loc[mask, "bid"].to_numpy() - ticks * rng.integers(1, 4, mask.sum()), 4)
        aq = _assign_ids(_with_received(aq, rng, "ALT"), "AQ", day)
        qcols = ["event_id", "symbol", "ts_exchange", "ts_received", "bid", "bid_size", "ask", "ask_size"]

        stamp = day.isoformat()
        arrived = datetime.combine(day, ref.SESSION_CLOSE) + timedelta(minutes=2)
        outputs = [
            ("PRIMARY", "trades", primary_trades),
            ("PRIMARY", "quotes", pq[qcols]),
            ("ALT", "trades", alt_trades_df),
            ("ALT", "quotes", aq[qcols]),
            ("VENDOR", "trades", vendor),
        ]
        for venue, stream, frame in outputs:
            rel = f"{venue}/{stream}/{stamp}.parquet"
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.reset_index(drop=True).to_parquet(target, index=False, compression="zstd")
            files.append(RawFile(rel, venue, stream, day, len(frame), arrived))

        # ---- Symbol master: one snapshot per day ---------------------------
        sc = ref.SYMBOL_CHANGE
        rows = []
        for inst in ref.INSTRUMENTS:
            if inst.instrument_id == sc["instrument_id"]:
                rows.append({"instrument_id": inst.instrument_id, "symbol": sc["old"], "sector": inst.sector,
                             "valid_from": ref.D1, "valid_to": sc["effective"] - timedelta(days=1)
                             if day >= sc["effective"] else None})
                if day >= sc["effective"]:
                    rows.append({"instrument_id": inst.instrument_id, "symbol": sc["new"], "sector": inst.sector,
                                 "valid_from": sc["effective"], "valid_to": None})
            else:
                rows.append({"instrument_id": inst.instrument_id, "symbol": inst.symbol, "sector": inst.sector,
                             "valid_from": ref.D1, "valid_to": None})
        master = pd.DataFrame(rows)
        rel = f"REF/symbol_master/{stamp}.parquet"
        (out_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        master.to_parquet(out_dir / rel, index=False, compression="zstd")
        master_arrived = sc["master_arrives"] if day == sc["effective"] else datetime.combine(day, datetime.min.time()) + timedelta(hours=6)
        files.append(RawFile(rel, "REF", "symbol_master", day, len(master), master_arrived))

    return files

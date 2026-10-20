"""Incidents, derived from what the pipeline found - not written by hand.

Each one carries when the defect started, when a check caught it, what it
touched, what was done, what stops it happening twice, and - from the
ablation - what it would have cost without the control that caught it.
"""

from __future__ import annotations

import pandas as pd

from src.app.pipeline import reference as ref
from src.app.pipeline.stages import PipelineResult


def _secs(a, b) -> float | None:
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return None
    return round((pd.Timestamp(b) - pd.Timestamp(a)).total_seconds(), 1)


def build_incidents(r: PipelineResult, ablation: pd.DataFrame) -> pd.DataFrame:
    q = r.quarantine
    t = r.trades
    ab = ablation.set_index("control")
    rows = []

    def counter(control: str) -> dict:
        if control not in ab.index:
            return {}
        a = ab.loc[control]
        return {"cf_bars_changed": int(a["bars_changed"]), "cf_orders_changed": int(a["orders_changed"]),
                "cf_pnl_delta": float(a["pnl_delta"]), "cf_worst_mark": float(a["desk_worst_mark"]),
                "cf_kill_switch": a["kill_switch"], "cf_crossed_fills": int(a["crossed_fills"])}

    # INC-01 duplicate burst
    d = q[q["check_id"] == "duplicate_trade_id"]
    if len(d):
        db = ref.DUP_BURST
        rows.append({
            "incident_id": "INC-01", "title": "ALT re-sent fifteen minutes of trades after a reconnect",
            "severity": "medium", "status": "resolved", "venue": "ALT", "stream": "trades",
            "check_id": "duplicate_trade_id", "control": "dedupe",
            "started_at": db["reconnect_at"], "detected_at": d["detected_at"].min(),
            "resolved_at": d["detected_at"].max(), "events_affected": len(d),
            "instruments_affected": int(d["instrument_key"].nunique()),
            "what_happened": f"After a reconnect at {db['reconnect_at']:%H:%M:%S} ALT replayed {len(d)} trades "
                             f"from {db['resend_from']:%H:%M} to {db['resend_to']:%H:%M} with new event ids and "
                             "their original trade ids.",
            "root_cause": "Venue-side replay on reconnect; event ids are per message, trade ids are per trade.",
            "response": "Every copy after the first dropped by trade id; first copies kept with their original timing.",
            "prevention": "Uniqueness on (venue, trade id) is part of the ALT and PRIMARY contracts; "
                          "test_dedupe_drops_resends_and_is_idempotent.",
            **counter("dedupe"),
        })

    # INC-02 / INC-03 feed gaps
    fills = t[t["flags"].str.contains("gap_fill", na=False) & (t["event_type"] == "trade")]
    for n, gap in enumerate(ref.FEED_GAPS, start=2):
        g = fills[(fills["ts_exchange"] >= pd.Timestamp(gap["start"])) & (fills["ts_exchange"] < pd.Timestamp(gap["end"]))]
        if not len(g):
            continue
        g = g.sort_values("ts_received")
        detected = g["ts_received"].iloc[min(4, len(g) - 1)]
        mins = int((pd.Timestamp(gap["end"]) - pd.Timestamp(gap["start"])).total_seconds() // 60)
        during_skew = gap["day"] >= ref.VENDOR_SKEW["from"].date()
        rows.append({
            "incident_id": f"INC-0{n}",
            "title": f"PRIMARY's direct feed went silent for {mins} minutes" + (" - while the vendor's clock was off" if during_skew else ""),
            "severity": "high", "status": "resolved", "venue": "PRIMARY", "stream": "trades",
            "check_id": "feed_gap", "control": "feed_arbitration",
            "started_at": gap["start"], "detected_at": detected, "resolved_at": gap["end"],
            "events_affected": len(g), "instruments_affected": int(g["instrument_key"].nunique()),
            "what_happened": f"No PRIMARY trades or quotes from {gap['start']:%H:%M} to {gap['end']:%H:%M} on "
                             f"{gap['day']:%d/%m}; the vendor's copy carried {len(g)} trades in that window."
                             + (" The vendor's timestamps were 1.8 s fast that day, so the fills used corrected times." if during_skew else ""),
            "root_cause": "Direct-feed session drop; the vendor's redundant copy was unaffected.",
            "response": "Arbitration filled the gap from the vendor feed by trade id; the gate degraded positions "
                        "to half a unit for the minutes running on the backup.",
            "prevention": "Feed-gap check: the vendor carrying trades PRIMARY has not, for five trades in a row; "
                          "test_arbitration_fills_gaps_by_trade_id.",
            **counter("feed_arbitration"),
        })

    # INC-04 vendor clock skew
    co = r.clock_offsets
    skew_days = co[co["applied_ms"] != 0]
    if len(skew_days):
        first = skew_days.iloc[0]
        neg = t[(t["source"] == "VENDOR") & (t["day"] == first["day"])
                & ((t["ts_received"] - t["ts_exchange_raw"]).dt.total_seconds() < -0.05)]
        rows.append({
            "incident_id": "INC-04", "title": "The vendor's clock ran 1.8 seconds fast",
            "severity": "medium", "status": "mitigated", "venue": "VENDOR", "stream": "trades",
            "check_id": "negative_latency", "control": "clock_offset",
            # The fault began before the open; nothing could see it until the first trade.
            "started_at": max(ref.VENDOR_SKEW["from"], pd.Timestamp.combine(first["day"], ref.SESSION_OPEN)),
            "detected_at": neg["ts_received"].min() if len(neg) else None,
            "resolved_at": first["estimated_at"], "events_affected": int(skew_days["negative_latency_before"].sum()),
            "instruments_affected": len(ref.INSTRUMENTS),
            "what_happened": f"From {first['day']:%d/%m} the vendor's exchange timestamps were {first['median_ms']:+.0f} ms "
                             "off PRIMARY's for the same trades, so its events appeared to arrive before they happened.",
            "root_cause": "Vendor-side clock fault (their NTP), not ours: our receive timestamps agree with PRIMARY's.",
            "response": f"Offset measured on the first 500 matched trades each day (MAD {first['mad_ms']:.1f} ms, inside the "
                        "contract's 20 ms tolerance) and removed before any vendor event was used. Raised with the vendor.",
            "prevention": "Negative-latency check plus a daily offset measured against PRIMARY by trade id, applied only "
                          "inside tolerance; test_clock_offset_measured_and_bounded.",
            **counter("clock_offset"),
        })

    # INC-05 bad print
    bp = q[q["check_id"] == "price_band"]
    if len(bp):
        row = bp.iloc[0]
        trade = t[t["event_id"] == row["event_id"]].iloc[0]
        shift = "ten times" if "+" in row["reason"].split(" is ")[1][:2] else "a tenth of"
        rows.append({
            "incident_id": "INC-05", "title": f"A decimal-shift print on {row['symbol']}, cancelled by the exchange",
            "severity": "critical", "status": "resolved", "venue": "PRIMARY", "stream": "trades",
            "check_id": "price_band", "control": "price_band",
            "started_at": trade["ts_exchange"], "detected_at": trade["ts_received"],
            "resolved_at": trade["ts_removed"], "events_affected": 1, "instruments_affected": 1,
            "what_happened": f"{row['symbol']} printed {int(trade['qty']):,} at ${trade['price']:.3f} on PRIMARY at "
                             f"{trade['ts_exchange']:%H:%M:%S} - {shift} the market. No other venue traded there. "
                             f"The exchange cancelled it at {trade['ts_removed']:%H:%M:%S}.",
            "root_cause": "Erroneous order at the venue; cancelled under the venue's error-trade rules.",
            "response": "Held by the price band on arrival, never published to a bar; the gate blocked the instrument "
                        "until the cancel arrived; the held print resolved as cancelled.",
            "prevention": "Price band with cross-venue confirmation, and cancels applied with bar restatement; "
                          "test_bad_print_never_reaches_a_bar.",
            **counter("price_band"),
        })

    # INC-06 schema drift
    sd = q[q["check_id"] == "schema"]
    if len(sd):
        rows.append({
            "incident_id": "INC-06", "title": "ALT renamed qty to size and added a field, unannounced",
            "severity": "high", "status": "open", "venue": "ALT", "stream": "trades",
            "check_id": "schema", "control": None,
            "started_at": sd["ts_exchange"].min(), "detected_at": sd["detected_at"].min(), "resolved_at": None,
            "events_affected": len(sd), "instruments_affected": int(sd["symbol"].nunique()),
            "what_happened": f"From the open on {ref.SCHEMA_DRIFT['from_day']:%d/%m} ALT's trades carry size instead of "
                             f"qty and a new liquidity_flag. {len(sd):,} trades over two sessions are held.",
            "root_cause": "Venue release without notice to subscribers.",
            "response": "Partitions quarantined whole - the pipeline does not guess what a renamed field means. "
                        "Consolidated volume runs on PRIMARY alone and the gate caps positions at half a unit. "
                        "Contract v2 is proposed with evidence; it needs approval by someone other than its proposer.",
            "prevention": "Unknown or missing fields quarantine the partition; contract changes are versioned and "
                          "approved; test_schema_drift_quarantines_the_partition.",
        })

    # INC-07 crossed book
    cb = q[q["check_id"] == "crossed_book"]
    if len(cb):
        rows.append({
            "incident_id": "INC-07", "title": "ALT's ask went stale while the bid moved through it",
            "severity": "medium", "status": "resolved", "venue": "ALT", "stream": "quotes",
            "check_id": "crossed_book", "control": "crossed_book_filter",
            "started_at": cb["ts_exchange"].min(), "detected_at": cb["detected_at"].min(),
            "resolved_at": cb["detected_at"].max(), "events_affected": len(cb),
            "instruments_affected": int(cb["instrument_key"].nunique()),
            "what_happened": f"{len(cb)} ALT quotes on {', '.join(sorted(cb['symbol'].unique()))} showed a bid at or above "
                             f"the ask between {cb['ts_exchange'].min():%H:%M} and {cb['ts_exchange'].max():%H:%M}.",
            "root_cause": "One side of ALT's book stopped updating.",
            "response": "Crossed quotes excluded from the consolidated book; the gate degraded the instruments while it lasted.",
            "prevention": "Crossed-book check on every quote; test_crossed_quotes_never_price_a_fill.",
            **counter("crossed_book_filter"),
        })

    # INC-08 late symbol master
    sk = q[q["check_id"] == "symbol_known"]
    if len(sk):
        sc = ref.SYMBOL_CHANGE
        rows.append({
            "incident_id": "INC-08", "title": f"{sc['old']} became {sc['new']}; the symbol master landed after the open",
            "severity": "medium", "status": "resolved", "venue": "REF", "stream": "symbol_master",
            "check_id": "symbol_known", "control": "symbol_master",
            "started_at": pd.Timestamp.combine(sc["effective"], ref.SESSION_OPEN), "detected_at": sk["detected_at"].min(),
            "resolved_at": sc["master_arrives"], "events_affected": len(sk), "instruments_affected": 1,
            "what_happened": f"Trading under {sc['new']} began at the open; the master that maps it to "
                             f"{sc['instrument_id']} arrived at {sc['master_arrives']:%H:%M:%S}.",
            "root_cause": "Reference-data delivery missed its 09:30 SLA.",
            "response": f"{len(sk)} events held, then released under {sc['instrument_id']} when the master arrived; the "
                        "series and any position carried straight through the change.",
            "prevention": "Everything keyed on instrument id through the dated master; unknown symbols held, never "
                          "guessed; test_symbol_change_keeps_one_instrument.",
            **counter("symbol_master"),
        })

    # Not an incident: the band doing its job on a genuine move.
    gm = ref.GENUINE_MOVE
    conf = t[t["flags"].str.contains("band_confirmed", na=False)]
    if len(conf):
        rows.append({
            "incident_id": "CHK-01", "title": f"{gm['symbol']} moved {gm['jump']:.0%} - flagged, confirmed, released",
            "severity": "info", "status": "no action", "venue": "PRIMARY", "stream": "trades",
            "check_id": "price_band", "control": None,
            "started_at": gm["at"], "detected_at": conf["ts_received"].min(), "resolved_at": conf["ts_available"].max(),
            "events_affected": len(conf), "instruments_affected": 1,
            "what_happened": f"{len(conf)} prints left the band within minutes of {gm['at']:%H:%M}; ALT and PRIMARY moved together.",
            "root_cause": "A genuine move.",
            "response": "Each print released as soon as an independent venue confirmed it.",
            "prevention": "Confirmation by an independent venue is what keeps the band from blocking the moves that "
                          "matter; test_genuine_move_is_released.",
        })

    out = pd.DataFrame(rows)
    out["ttd_seconds"] = [_secs(a, b) for a, b in zip(out["started_at"], out["detected_at"])]
    return out

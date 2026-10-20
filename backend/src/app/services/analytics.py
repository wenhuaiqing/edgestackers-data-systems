"""Read queries behind every page. Routers stay thin; the SQL lives here."""

from __future__ import annotations

import json
from datetime import datetime

from src.app.pipeline import contracts as ct
from src.app.pipeline import reference as ref
from src.app.services import db

CHECKS = [
    {"check_id": "schema", "applies_to": "every partition",
     "what": "Fields match the contract version in force: nothing required missing, nothing unknown.",
     "on_fail": "Quarantine the whole partition until the contract changes", "tier": 1},
    {"check_id": "duplicate_trade_id", "applies_to": "PRIMARY, ALT trades",
     "what": "A trade id is accepted once per venue; later copies are dropped.",
     "on_fail": "Drop the copy, keep the first", "tier": 1},
    {"check_id": "negative_latency", "applies_to": "every stream",
     "what": "An event cannot be received more than 50 ms before it happened.",
     "on_fail": "Measure the feed's clock against PRIMARY; correct inside tolerance, hold outside it", "tier": 1},
    {"check_id": "clock_offset", "applies_to": "VENDOR trades",
     "what": "Daily offset against PRIMARY on the first 500 matched trades; applied only if the MAD is under 20 ms.",
     "on_fail": "Hold the vendor feed rather than trust its timestamps", "tier": 1},
    {"check_id": "feed_gap", "applies_to": "PRIMARY trades",
     "what": "The vendor carrying trades PRIMARY has not delivered, five in a row.",
     "on_fail": "Fill from the vendor by trade id; degrade the gate while on the backup", "tier": 1},
    {"check_id": "price_band", "applies_to": "PRIMARY, ALT trades",
     "what": "A print more than 8% from the five-minute median is held until an independent venue confirms it.",
     "on_fail": "Hold the print; block the instrument at the gate until confirmed or cancelled", "tier": 1},
    {"check_id": "cancel_applied", "applies_to": "PRIMARY, ALT trades",
     "what": "Exchange cancels remove the trade and restate any bar it was in.",
     "on_fail": "Restate the bar; log the restatement", "tier": 1},
    {"check_id": "crossed_book", "applies_to": "PRIMARY, ALT quotes",
     "what": "A quote with the bid at or above the ask cannot be traded against.",
     "on_fail": "Exclude it from the consolidated book; degrade the gate", "tier": 1},
    {"check_id": "symbol_known", "applies_to": "every stream",
     "what": "Every symbol resolves to an instrument through the symbol master in force when the event arrived.",
     "on_fail": "Hold the event until the master arrives; never guess", "tier": 1},
    {"check_id": "watermark", "applies_to": "bars",
     "what": "A bar is published 3 s after its minute; anything later restates it.",
     "on_fail": "Restate and log; decisions keep the bar as first published", "tier": 2},
]


def _j(v):
    return json.loads(v) if isinstance(v, str) and v[:1] in "[{" else v


def meta_counts() -> dict:
    return {
        "events": int(db.scalar("SELECT sum(rows) FROM raw_files")),
        "files": int(db.scalar("SELECT count(*) FROM raw_files")),
        "bars": int(db.scalar("SELECT count(*) FROM bars")),
    }


def overview() -> dict:
    q_by_check = db.rows("""SELECT check_id, count(*) AS n,
                                   count(*) FILTER (WHERE resolution LIKE 'held until%' OR resolution LIKE 'held pending%') AS still_held
                            FROM quarantine GROUP BY 1 ORDER BY n DESC""")
    pnl = db.rows("SELECT model_id, sum(pnl) AS pnl, sum(orders) AS orders FROM pnl_daily GROUP BY 1 ORDER BY 1")
    incidents = db.rows("""SELECT incident_id, title, severity, status, venue, check_id, detected_at, ttd_seconds
                           FROM incidents ORDER BY started_at""")
    feeds = db.rows("""
        SELECT source,
               count(*) AS events,
               quantile_cont(epoch_ms(ts_received) - epoch_ms(ts_exchange_raw), 0.99) AS p99_ms,
               count(*) FILTER (WHERE status IN ('duplicate', 'held')) AS rejected,
               count(*) FILTER (WHERE status = 'redundant') AS standby
        FROM trades
        -- A re-sent copy is not a slow delivery: latency is measured on first copies.
        WHERE status <> 'duplicate'
        GROUP BY 1 ORDER BY 1""")
    partitions = db.rows("""SELECT venue, stream, count(*) AS partitions, count(*) FILTER (WHERE NOT ok) AS quarantined
                            FROM raw_files GROUP BY 1, 2 ORDER BY 1, 2""")
    gate_days = db.rows("""SELECT day, count(*) FILTER (WHERE state = 'open') AS open,
                                  count(*) FILTER (WHERE state = 'degraded') AS degraded,
                                  count(*) FILTER (WHERE state = 'blocked') AS blocked
                           FROM gate GROUP BY 1 ORDER BY 1""")
    headline = db.rows("SELECT * FROM ablation WHERE control = 'price_band'")
    proposal = db.rows("SELECT proposal_id, subject, status, proposed_by, summary FROM proposals")
    promotion = _j(db.kv("promotion"))
    return {
        "week": [ref.TRADING_DAYS[0].isoformat(), ref.TRADING_DAYS[-1].isoformat()],
        "counts": {
            **meta_counts(),
            "quarantined": int(db.scalar("SELECT count(*) FROM quarantine")),
            "restated": int(db.scalar("SELECT count(*) FROM restatements")),
            "incidents": len([i for i in incidents if i["incident_id"].startswith("INC")]),
            "open_incidents": len([i for i in incidents if i["status"] == "open"]),
        },
        "quarantine_by_check": q_by_check,
        "pnl": pnl,
        "incidents": incidents,
        "feeds": feeds,
        "partitions": partitions,
        "gate_days": gate_days,
        "headline": headline[0] if headline else None,
        "proposals": proposal,
        "promotion": {"eligible": promotion["eligible"], "checks": promotion["checks"]} if promotion else None,
        "runs": db.rows("SELECT run_id, kind, trigger, started_at, wall_ms, cost_aud FROM runs ORDER BY started_at DESC LIMIT 3"),
    }


def feeds() -> dict:
    contracts = db.rows("SELECT * FROM contracts ORDER BY contract_id")
    for c in contracts:
        c["consumers"] = _j(c["consumers"])
        c["sla"] = _j(c["sla"])
        doc = ct.load_all()[c["contract_id"]]
        c["versions"] = [{"version": v["version"], "status": v["status"], "effective_from": str(v["effective_from"]),
                          "approved_by": v.get("approved_by", ""), "fields": v["fields"]} for v in doc["versions"]]
        c["mapping"] = doc.get("mapping")
        c["clock_offset"] = doc.get("clock_offset")
    platform_versions = db.rows("SELECT * FROM contract_versions WHERE source = 'platform' ORDER BY contract_id, version")
    for v in platform_versions:
        v["fields"] = _j(v["fields"])
    latency = db.rows("""
        SELECT source, day, count(*) AS events,
               quantile_cont(epoch_ms(ts_received) - epoch_ms(ts_exchange_raw), 0.50) AS p50_ms,
               quantile_cont(epoch_ms(ts_received) - epoch_ms(ts_exchange_raw), 0.99) AS p99_ms,
               avg(CASE WHEN epoch_ms(ts_received) - epoch_ms(ts_exchange_raw) < -50 THEN 1 ELSE 0 END) AS negative_share,
               avg(CASE WHEN epoch_ms(ts_received) - epoch_ms(ts_exchange_raw) > 3000 THEN 1 ELSE 0 END) AS late_share
        FROM trades WHERE status <> 'duplicate' GROUP BY 1, 2 ORDER BY 1, 2""")
    files = db.rows("SELECT * FROM raw_files ORDER BY day, venue, stream")
    proposals = db.rows("SELECT * FROM proposals ORDER BY proposed_at")
    for p in proposals:
        p["evidence"] = _j(p["evidence"])
        p["preview"] = _j(p["preview"])
    return {"contracts": contracts, "platform_versions": platform_versions, "latency": latency,
            "clock_offsets": db.rows("SELECT * FROM clock_offsets ORDER BY day"), "files": files,
            "proposals": proposals}


def pipeline() -> dict:
    latest = db.scalar("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1")
    return {
        "run_id": latest,
        "stages": db.rows("SELECT * FROM run_stages WHERE run_id = ? ORDER BY seq", [latest]),
        "runs": db.rows("SELECT * FROM runs ORDER BY started_at DESC"),
        "restatements": db.rows("""SELECT r.*, i.symbol FROM restatements r
                                   LEFT JOIN instruments i ON i.instrument_id = r.instrument_key
                                   ORDER BY minute"""),
        "partitions": db.rows("SELECT * FROM partition_hashes ORDER BY partition"),
        "status_counts": db.rows("SELECT source, status, count(*) AS n FROM trades GROUP BY 1, 2 ORDER BY 1, 2"),
        "instruments": db.rows("SELECT instrument_id, symbol, sector FROM instruments ORDER BY symbol"),
    }


def lineage(instrument: str, minute: str) -> dict:
    m = datetime.fromisoformat(minute)
    bar = db.rows("SELECT * FROM bars WHERE instrument_key = ? AND minute = ?", [instrument, m])
    events = db.rows("""
        SELECT t.event_id, t.source, t.venue, t.trade_id, t.symbol, t.event_type, t.ts_exchange, t.ts_exchange_raw,
               t.ts_received, t.ts_available, t.ts_removed, t.price, t.qty, t.side, t.status, t.flags,
               t.offset_ms, t.file, t.raw_row,
               (t.ts_available <= ? + INTERVAL 63 SECOND
                AND (t.ts_removed IS NULL OR t.ts_removed > ? + INTERVAL 63 SECOND)
                AND t.status IN ('accepted', 'cancelled') AND t.event_type = 'trade') AS in_published,
               (t.ts_removed IS NULL AND t.status = 'accepted' AND t.event_type = 'trade') AS in_final
        FROM trades t
        WHERE t.instrument_key = ? AND date_trunc('minute', t.ts_exchange) = ?
        ORDER BY t.ts_exchange, t.source""", [m, m, instrument, m])
    quarantine = db.rows("""SELECT * FROM quarantine WHERE instrument_key = ? AND date_trunc('minute', ts_exchange) = ?""",
                         [instrument, m])
    book = db.rows("SELECT * FROM book WHERE instrument_key = ? AND minute = ?", [instrument, m])
    gate = db.rows("SELECT state, reason FROM gate WHERE instrument_key = ? AND minute = ?", [instrument, m])
    files = sorted({e["file"] for e in events})
    file_rows = db.rows(f"SELECT file, sha256, rows, contract, version, ok FROM raw_files WHERE file IN ({','.join('?' * len(files))})",
                        files) if files else []
    restated = db.rows("SELECT * FROM restatements WHERE instrument_key = ? AND minute = ?", [instrument, m])
    orders = db.rows("""SELECT * FROM orders WHERE instrument_key = ? AND (decided_at = ? OR executed_at = ?)
                        ORDER BY executed_at""", [instrument, m, m])
    run = db.rows("SELECT run_id, git_sha, contract_versions, started_at FROM runs ORDER BY started_at DESC LIMIT 1")
    return {"instrument": instrument, "minute": minute, "bar": bar[0] if bar else None, "events": events,
            "quarantine": quarantine, "book": book[0] if book else None, "gate": gate[0] if gate else None,
            "files": file_rows, "restatement": restated[0] if restated else None, "orders": orders,
            "run": run[0] if run else None}


def bars_day(instrument: str, day: str) -> dict:
    series = db.rows("""
        SELECT b.minute, b.pub_close, b.close, b.pub_volume, b.volume, b.pub_vwap, b.restated, b.gap_fill_trades,
               g.state AS gate, g.reason AS gate_reason, e.position, bk.best_bid, bk.best_ask
        FROM bars b
        LEFT JOIN gate g USING (instrument_key, minute)
        LEFT JOIN book bk USING (instrument_key, minute)
        LEFT JOIN equity e ON e.instrument_key = b.instrument_key AND e.minute = b.minute AND e.model_id = 'mr-v1'
        WHERE b.instrument_key = ? AND b.day = ?
        ORDER BY b.minute""", [instrument, day])
    held = db.rows("""SELECT event_id, check_id, reason, ts_exchange, resolution FROM quarantine
                      WHERE instrument_key = ? AND day = ? AND stream = 'trades' ORDER BY ts_exchange LIMIT 50""",
                   [instrument, day])
    return {"instrument": instrument, "day": day, "series": series, "held": held}


def quality() -> dict:
    counts = db.rows("""SELECT check_id, venue, day, count(*) AS n FROM quarantine GROUP BY 1, 2, 3 ORDER BY 3, 1""")
    totals = {r["check_id"]: r["n"] for r in db.rows("SELECT check_id, count(*) AS n FROM quarantine GROUP BY 1")}
    incidents = db.rows("SELECT incident_id, check_id, title FROM incidents")
    catalogue = []
    for c in CHECKS:
        c = dict(c)
        c["fired"] = totals.get(c["check_id"], 0)
        c["incidents"] = [i["incident_id"] for i in incidents if i["check_id"] == c["check_id"]]
        catalogue.append(c)
    restated = int(db.scalar("SELECT count(*) FROM restatements"))
    for c in catalogue:
        if c["check_id"] == "watermark":
            c["fired"] = restated
        if c["check_id"] == "negative_latency":
            c["fired"] = int(db.scalar("SELECT sum(negative_latency_before) FROM clock_offsets"))
        if c["check_id"] == "feed_gap":
            c["fired"] = int(db.scalar("SELECT count(*) FROM trades WHERE flags LIKE '%gap_fill%'"))
        if c["check_id"] == "cancel_applied":
            c["fired"] = int(db.scalar("SELECT count(*) FROM trades WHERE status = 'cancelled'"))
        if c["check_id"] == "clock_offset":
            c["fired"] = int(db.scalar("SELECT count(*) FROM clock_offsets WHERE applied_ms <> 0"))
    return {"catalogue": catalogue, "counts": counts}


def quarantine_rows(check: str | None, venue: str | None, day: str | None, limit: int = 200) -> list[dict]:
    where, params = [], []
    if check:
        where.append("check_id = ?"); params.append(check)
    if venue:
        where.append("venue = ?"); params.append(venue)
    if day:
        where.append("day = ?"); params.append(day)
    sql = "SELECT * FROM quarantine" + (" WHERE " + " AND ".join(where) if where else "") + \
          f" ORDER BY ts_exchange LIMIT {min(int(limit), 500)}"
    return db.rows(sql, params)


def incidents() -> dict:
    rows = db.rows("SELECT * FROM incidents ORDER BY started_at")
    alerts = {a["incident_id"]: a["alert_id"] for a in db.rows("SELECT alert_id, incident_id FROM alerts")}
    for r in rows:
        r["alert_id"] = alerts.get(r["incident_id"])
    return {"incidents": rows}


def decisions() -> dict:
    desk = db.rows("""SELECT model_id, minute, sum(equity) AS equity, sum(abs(position * close)) AS gross
                      FROM equity GROUP BY 1, 2 ORDER BY 1, 2""")
    gate_orders = db.rows("""SELECT model_id, gate, reason, count(*) AS n FROM orders GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC""")
    trips = db.rows("""SELECT model_id, count(*) AS trips, avg(pnl) AS avg_pnl, avg(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS hit_rate,
                              sum(pnl) AS pnl FROM round_trips GROUP BY 1 ORDER BY 1""")
    return {
        "models": db.rows("SELECT * FROM model_registry ORDER BY model_id"),
        "pnl_daily": db.rows("SELECT * FROM pnl_daily ORDER BY model_id, day"),
        "desk": desk,
        "gate_orders": gate_orders,
        "gate_days": db.rows("""SELECT day, state, reason, count(*) AS minutes FROM gate WHERE state <> 'open'
                                GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC"""),
        "round_trips": trips,
        "kill_switch": db.rows("SELECT * FROM kill_switch"),
        "promotion": _j(db.kv("promotion")),
        "limits": {"unit_notional": 50000, "desk_loss_limit": 20000, "brokerage_bp": 0.5, "max_hold_minutes": 20},
    }


def orders(instrument: str | None, day: str | None, model: str = "mr-v1", limit: int = 300) -> list[dict]:
    where, params = ["o.model_id = ?"], [model]
    if instrument:
        where.append("o.instrument_key = ?"); params.append(instrument)
    if day:
        where.append("CAST(o.executed_at AS DATE) = ?"); params.append(day)
    return db.rows(f"""SELECT o.*, i.symbol FROM orders o LEFT JOIN instruments i ON i.instrument_id = o.instrument_key
                       WHERE {' AND '.join(where)} ORDER BY o.executed_at LIMIT {min(int(limit), 1000)}""", params)


def ablation() -> dict:
    rows = db.rows("SELECT * FROM ablation")
    for r in rows:
        r["verdict"] = _verdict(r)
    return {"rows": rows, "governed_pnl": rows[0]["governed_pnl"] if rows else None,
            "governed_worst_mark": rows[0]["governed_worst_mark"] if rows else None}


def _verdict(r: dict) -> str:
    if r["kill_switch"]:
        return "prevented a desk stop"
    if r["control"] == "quality_gate":
        return "cost P&L this week - by design"
    if r["bars_changed"] > 50:
        return "protects live bars"
    if r["research_bars_changed"] > 50:
        return "protects research history"
    if r["orders_changed"] > 0:
        return "changed orders at the margin"
    if r.get("crossed_fills_delta"):
        return "changed fill prices"
    return "insurance this week"


def operations(timings: list[dict]) -> dict:
    return {
        "timings": timings,
        "runs": db.rows("SELECT * FROM runs ORDER BY started_at DESC"),
        "stages": db.rows("SELECT * FROM run_stages ORDER BY run_id DESC, seq"),
        "audit": db.rows("SELECT * FROM audit_log ORDER BY ts DESC LIMIT 100"),
        "triage_runs": db.rows("""SELECT run_id, ts, alert_id, engine, model, ms, steps, grade FROM triage_runs
                                  ORDER BY ts DESC LIMIT 50"""),
        "build_seconds": db.kv("build_seconds"),
    }

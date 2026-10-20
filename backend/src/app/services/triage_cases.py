"""Labelled cases for the triage eval.

  real      the nine alerts the week's data actually raised
  variants  each real alert again under another instrument and session, so
            a verdict cannot lean on remembering one symbol
  hard      six cases built to separate reasoning from pattern-matching on
            the check's name - each one is wrong under the runbook:

    H1  negative latency on the vendor, but the vendor agrees with PRIMARY:
        our own receive clock is wrong. Applying an offset would hide it.
    H2  repeated trade ids whose copies differ in price and quantity: an id
        collision, not a resend. Dropping the copies drops real trades.
    H3  PRIMARY silent and so is every other feed: a halt. Nothing to fill.
    H4  a print outside the band on PRIMARY and on the vendor's copy of
        PRIMARY - one venue, not two. Still a bad print.
    H5  a symbol no master will ever list, with the master on time: not late
        reference data. A hold would wait for ever.
    H6  a move confirmed on ALT, then fully reversed, with a cancel on
        PRIMARY: the evidence conflicts. Escalate.
"""

from __future__ import annotations

import copy
import json

LABELS = {
    "INC-01": ("duplicate_resend", "dedupe_keep_first"),
    "INC-02": ("feed_gap", "fill_from_backup_feed"),
    "INC-03": ("feed_gap", "fill_from_backup_feed"),
    "INC-04": ("clock_skew", "apply_measured_offset"),
    "INC-05": ("bad_print", "hold_and_await_cancel"),
    "INC-06": ("schema_drift", "propose_contract_version"),
    "INC-07": ("crossed_book", "exclude_quotes"),
    "INC-08": ("late_reference_data", "hold_until_reference_arrives"),
    "CHK-01": ("genuine_move", "no_action"),
}

# Renames for the variants: every symbol and session is swapped consistently.
VARIANTS = [
    {"MURR": "OTWA", "KOSC": "LACH", "EYRA": "GAWZ", "EYRE": "GAWL", "IRON": "HUON", "QUIL": "ROPE",
     "BRIG": "TWEE", "NAMO": "DUNE", "INS-013": "INS-015", "INS-011": "INS-012", "INS-005": "INS-007",
     "2026-10-1": "2026-09-2"},
    {"MURR": "PEEL", "KOSC": "SNOW", "EYRA": "CALX", "EYRE": "CALD", "IRON": "FLIN", "QUIL": "JARR",
     "BRIG": "ALBA", "NAMO": "BRIG", "INS-013": "INS-016", "INS-011": "INS-019", "INS-005": "INS-003",
     "2026-10-1": "2026-09-0"},
]


def _swap(text: str, mapping: dict[str, str]) -> str:
    for a, b in mapping.items():
        text = text.replace(a, b)
    return text


def build_cases(alerts: list[dict]) -> list[dict]:
    cases: list[dict] = []
    by_incident = {a["incident_id"]: a for a in alerts}
    for a in alerts:
        cat, action = LABELS[a["incident_id"]]
        base = {"alert_id": a["alert_id"], "check_id": a["check_id"], "venue": a["venue"], "stream": a["stream"],
                "day": str(a["day"])[:10], "summary": a["summary"], "world": json.loads(a["world"])}
        cases.append({"case_id": f"real-{a['incident_id']}", "kind": "real", "label": {"category": cat, "action": action},
                      "alert": base})
        for n, mapping in enumerate(VARIANTS, start=1):
            text = _swap(json.dumps(base), mapping)
            cases.append({"case_id": f"var{n}-{a['incident_id']}", "kind": "variant",
                          "label": {"category": cat, "action": action}, "alert": json.loads(text)})
    cases += _hard(by_incident)
    return cases


def _alert(a: dict) -> dict:
    return {"alert_id": a["alert_id"], "check_id": a["check_id"], "venue": a["venue"], "stream": a["stream"],
            "day": str(a["day"])[:10], "summary": a["summary"], "world": copy.deepcopy(json.loads(a["world"]))}


def _hard(by: dict) -> list[dict]:
    out = []

    if "INC-04" in by:
        h = _alert(by["INC-04"])
        w = h["world"]
        w["get_cross_feed_alignment"].update({"median_ms": 0.6, "mad_ms": 0.4, "full_day_median_ms": 0.5})
        w["get_feed_latency"].update({"negative_share": 0.62, "p50_ms": -38.0})
        w["get_feed_latency_note"] = None
        for s in w["get_samples"]:
            s["latency_ms"] = -41.0
        w.pop("get_feed_latency_note")
        h["summary"] = "negative_latency: VENDOR events stamped as received before they happened"
        out.append({"case_id": "hard-H1-own-clock", "kind": "hard",
                    "label": {"category": "unknown", "action": "escalate_to_human"}, "alert": h,
                    "why": "The vendor agrees with PRIMARY to the millisecond; the fault is our receive clock."})

    if "INC-01" in by:
        h = _alert(by["INC-01"])
        w = h["world"]
        w["get_duplicate_stats"]["same_price_and_qty_on_every_copy"] = False
        for i, s in enumerate(w["get_samples"]):
            if s.get("price") is not None:
                s["price"] = round(s["price"] * (1 + 0.004 * (i + 1)), 2)
            if s.get("qty") is not None:
                s["qty"] = float(s["qty"]) + 300 * (i + 1)
        out.append({"case_id": "hard-H2-id-collision", "kind": "hard",
                    "label": {"category": "unknown", "action": "escalate_to_human"}, "alert": h,
                    "why": "Copies differ in price and quantity: the venue reused trade ids. Dropping them drops real trades."})

    if "INC-02" in by:
        h = _alert(by["INC-02"])
        w = h["world"]
        for m in w["get_feed_activity"]["per_minute"]:
            if "14:05" <= m["minute"] < "14:11":
                m.update({"primary_direct": 0, "vendor": 0, "vendor_only": 0, "alt": 0})
        w["get_samples"] = []
        h["summary"] = "feed_gap: PRIMARY delivered no trades for six minutes"
        out.append({"case_id": "hard-H3-halt", "kind": "hard",
                    "label": {"category": "venue_halt", "action": "no_action"}, "alert": h,
                    "why": "Every feed is silent at once: a halt. There is nothing to fill."})

    if "INC-05" in by:
        h = _alert(by["INC-05"])
        w = h["world"]
        prim = w["get_price_context"]["by_venue"].get("PRIMARY", {})
        w["get_price_context"]["by_venue"]["VENDOR"] = {**prim}
        out.append({"case_id": "hard-H4-vendor-is-not-a-venue", "kind": "hard",
                    "label": {"category": "bad_print", "action": "hold_and_await_cancel"}, "alert": h,
                    "why": "The vendor's copy of PRIMARY is not an independent venue. Two rows, one market."})

    if "INC-08" in by:
        h = _alert(by["INC-08"])
        w = h["world"]
        text = json.dumps(w).replace("EYRA", "MURR.X")
        w = json.loads(text)
        w["get_reference_data"]["symbol_master_arrived_at"] = w["get_reference_data"]["symbol_master_arrived_at"][:11] + "06:00:00.000"
        w["get_reference_data"].pop("previous_symbol_for_instrument", None)
        w["get_reference_data"]["instrument_after_master"] = None
        h["world"] = w
        h["summary"] = "symbol_known: events for MURR.X, a symbol the master in force does not list"
        out.append({"case_id": "hard-H5-never-valid", "kind": "hard",
                    "label": {"category": "unknown", "action": "escalate_to_human"}, "alert": h,
                    "why": "The master arrived on time and no version lists the symbol: holding would wait for ever."})

    if "CHK-01" in by:
        h = _alert(by["CHK-01"])
        w = h["world"]
        pc = w["get_price_context"]
        pc["median_price_1_to_10_min_after"] = pc["five_minute_median_before"]
        pc["cancels_received"] = 1
        out.append({"case_id": "hard-H6-conflicting", "kind": "hard",
                    "label": {"category": "unknown", "action": "escalate_to_human"}, "alert": h,
                    "why": "Confirmed on ALT, yet fully reversed with a cancel on PRIMARY: the evidence conflicts."})
    return out

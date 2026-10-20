"""Alert triage: an agent that investigates with tools, a rules baseline it
has to beat, and a grader that checks both against labelled cases.

The agent
  - reads the alert, chooses which of nine tools to call (each answers from
    the snapshot frozen when the alert fired), and submits a typed verdict
  - at most five steps; the last one is forced to submit
  - proposes; it never changes data. Every action it names is a proposal a
    person approves.

The rules baseline is the on-call runbook: map the check that fired to its
usual cause, with the one refinement a runbook would have (a price-band
alert confirmed on two venues is a genuine move).

The grader marks a verdict right only if the category and action match the
label, every piece of evidence quotes something the tools actually returned,
and the action does no harm - blocking a genuine move, or waving a bad print
through, fails however well it is argued.
"""

from __future__ import annotations

import json
import re
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from src.app.pipeline.alerts import TOOL_NAMES
from src.app.services import llm

Category = Literal["duplicate_resend", "feed_gap", "clock_skew", "bad_print", "genuine_move", "schema_drift",
                   "crossed_book", "late_reference_data", "venue_halt", "unknown"]
Action = Literal["dedupe_keep_first", "fill_from_backup_feed", "apply_measured_offset", "hold_and_await_cancel",
                 "no_action", "propose_contract_version", "exclude_quotes", "hold_until_reference_arrives",
                 "escalate_to_human"]

ACTION_FOR: dict[str, str] = {
    "duplicate_resend": "dedupe_keep_first",
    "feed_gap": "fill_from_backup_feed",
    "clock_skew": "apply_measured_offset",
    "bad_print": "hold_and_await_cancel",
    "genuine_move": "no_action",
    "schema_drift": "propose_contract_version",
    "crossed_book": "exclude_quotes",
    "late_reference_data": "hold_until_reference_arrives",
    "venue_halt": "no_action",
    "unknown": "escalate_to_human",
}


class TriageResult(BaseModel):
    category: Category
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1, max_length=4,
                                description="Each item quotes a specific value a tool returned.")
    proposed_action: Action
    affects_trading: bool
    instruments_to_gate: list[str] = Field(default_factory=list, max_length=10)
    summary: str = Field(max_length=400)


SYSTEM = """You triage data-quality alerts for the market-data platform behind a trading desk.

A check has fired. Investigate with the tools - each answers from a snapshot taken when the alert fired - then submit one verdict with submit_triage.

Categories (pick the one the evidence supports, not the one the check's name suggests):
- duplicate_resend: the same trade ids received again with new event ids, every copy the same price and quantity.
- feed_gap: one feed silent while a redundant feed still carries its trades.
- venue_halt: every feed silent at once for the instrument or venue - nothing is missing, nothing traded.
- clock_skew: a feed's timestamps sit a consistent offset from a reference feed for the same trades (low MAD).
- bad_print: one print far from the market, not confirmed by an independent venue (a vendor copy of the same venue is not independent).
- genuine_move: a large move confirmed by an independent venue and sustained afterwards.
- schema_drift: a partition's fields differ from its contract (renamed, added or missing).
- crossed_book: a venue's quotes show the bid at or above the ask.
- late_reference_data: events for a symbol the reference data in force does not yet list, and the reference data arrived late.
- unknown: nothing fits, or the evidence conflicts.

Actions: duplicate_resend -> dedupe_keep_first; feed_gap -> fill_from_backup_feed; venue_halt -> no_action; clock_skew -> apply_measured_offset; bad_print -> hold_and_await_cancel; genuine_move -> no_action; schema_drift -> propose_contract_version; crossed_book -> exclude_quotes; late_reference_data -> hold_until_reference_arrives; unknown -> escalate_to_human.
If your confidence is below 0.6, or the evidence conflicts, choose unknown and escalate_to_human. An unnecessary hold stops the desk trading; a missed bad print loses money. Neither is safe.

Evidence: one to four short statements, each quoting a specific value a tool returned (a number, field name, id or time). Never state a value you did not see.
You propose; a person approves. Do not claim to have changed anything."""

TOOL_DOCS = {
    "get_samples": "Up to five of the events that tripped the check.",
    "get_feed_latency": "Receive minus exchange time for the alert's feed that day: p50/p95/p99, negative and late shares.",
    "get_cross_feed_alignment": "Vendor exchange time minus PRIMARY exchange time for the same trades: median, MAD, matched count.",
    "get_contract_diff": "The partition's observed fields against its data contract: missing and unknown fields.",
    "get_price_context": "Prints around the alert by venue against the five-minute median, cancels received, and the price after.",
    "get_duplicate_stats": "Repeated trade ids for the venue that day: counts, timing, whether copies match.",
    "get_book_state": "Quotes around the alert: crossed quotes by venue, when, which symbols.",
    "get_reference_data": "Symbol master arrival and whether the symbol was known when its events arrived.",
    "get_feed_activity": "Trades per minute around the alert: PRIMARY direct, vendor, vendor-only, ALT.",
}


def _tools() -> list[dict]:
    tools = [{"type": "function", "function": {"name": n, "description": TOOL_DOCS[n],
                                               "parameters": {"type": "object", "properties": {}}}}
             for n in TOOL_NAMES]
    schema = TriageResult.model_json_schema()
    schema.pop("title", None)
    tools.append({"type": "function", "function": {
        "name": "submit_triage", "description": "Submit the verdict. Call once, last.", "parameters": schema}})
    return tools


MAX_STEPS = 5


def run_agent(alert: dict) -> dict:
    """Investigate an alert with the LLM. Returns verdict, trace and timings."""
    world = alert["world"] if isinstance(alert["world"], dict) else json.loads(alert["world"])
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Alert {alert.get('alert_id', '')}: {alert['summary']}. "
                                    f"Venue {alert.get('venue')}, stream {alert.get('stream')}, day {alert.get('day')}."},
    ]
    trace: list[dict] = []
    retrieved: dict[str, object] = {}
    model_used = None
    t0 = time.perf_counter()
    tools = _tools()
    for step in range(MAX_STEPS):
        last = step == MAX_STEPS - 1
        choice = {"type": "function", "function": {"name": "submit_triage"}} if last else "required"
        completion, model_used = llm.call(lambda m, c: c.chat.completions.create(
            model=m, messages=messages, tools=tools, tool_choice=choice, temperature=0.0))
        msg = completion.choices[0].message
        calls = msg.tool_calls or []
        if not calls:
            trace.append({"step": step + 1, "kind": "text", "content": (msg.content or "")[:400]})
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": "Call a tool, or submit_triage."})
            continue
        # Echo the message as received, extra fields and all: Gemini 3 attaches
        # a thought signature to each tool call and refuses the next turn
        # without it. Rebuilding the message from its known fields drops it.
        echoed = msg.model_dump(exclude_none=True)
        echoed["content"] = echoed.get("content") or ""
        messages.append(echoed)
        for c in calls:
            name = c.function.name
            if name == "submit_triage":
                try:
                    result = TriageResult.model_validate_json(c.function.arguments or "{}")
                except ValidationError as exc:
                    trace.append({"step": step + 1, "kind": "invalid_submit", "error": str(exc)[:300]})
                    messages.append({"role": "tool", "tool_call_id": c.id,
                                     "content": json.dumps({"error": "invalid verdict", "detail": str(exc)[:500]})})
                    continue
                trace.append({"step": step + 1, "kind": "submit", "verdict": result.model_dump()})
                return {"engine": "agent", "model": model_used, "result": result.model_dump(), "trace": trace,
                        "retrieved": retrieved, "steps": step + 1, "ms": round((time.perf_counter() - t0) * 1000)}
            payload = world.get(name, {"error": f"no tool named {name}"})
            retrieved[name] = payload
            trace.append({"step": step + 1, "kind": "tool", "tool": name})
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(payload, default=str)[:6000]})
    raise RuntimeError("The agent did not submit a verdict within its step budget.")


def run_rules(alert: dict) -> dict:
    """The runbook baseline: the check that fired decides, with one refinement."""
    world = alert["world"] if isinstance(alert["world"], dict) else json.loads(alert["world"])
    check = alert.get("check_id")
    t0 = time.perf_counter()
    ev: list[str] = []
    if check == "schema":
        d = world.get("get_contract_diff", {})
        cat = "schema_drift"
        ev.append(f"missing {d.get('missing_required')}, unknown {d.get('unknown_fields')}")
    elif check == "duplicate_trade_id":
        d = world.get("get_duplicate_stats", {})
        cat = "duplicate_resend"
        ev.append(f"{d.get('copies_beyond_first')} copies beyond the first")
    elif check == "negative_latency":
        d = world.get("get_cross_feed_alignment", {})
        cat = "clock_skew"
        ev.append(f"median offset {d.get('median_ms')} ms")
    elif check == "feed_gap":
        d = world.get("get_feed_activity", {})
        n = sum(m.get("vendor_only", 0) for m in d.get("per_minute", []))
        cat = "feed_gap"
        ev.append(f"{n} vendor_only trades in the window")
    elif check == "price_band":
        d = world.get("get_price_context", {})
        outside = [v for v, s in (d.get("by_venue") or {}).items() if s.get("outside_band")]
        cat = "genuine_move" if len(outside) >= 2 else "bad_print"
        ev.append(f"outside the band on {', '.join(outside) or 'no venue'}")
    elif check == "crossed_book":
        d = world.get("get_book_state", {})
        cat = "crossed_book"
        ev.append(f"{d.get('crossed_quotes')} crossed quotes")
    elif check == "symbol_known":
        d = world.get("get_reference_data", {})
        cat = "late_reference_data"
        ev.append(f"master arrived {d.get('symbol_master_arrived_at')}")
    else:
        cat = "unknown"
        ev.append(f"no runbook entry for {check}")
    result = TriageResult(category=cat, confidence=0.9 if cat != "unknown" else 0.3, evidence=ev,
                          proposed_action=ACTION_FOR[cat], affects_trading=cat not in ("genuine_move", "venue_halt"),
                          summary=f"Runbook: {check} -> {cat}.")
    return {"engine": "rules", "model": "runbook", "result": result.model_dump(),
            "trace": [{"step": 1, "kind": "rule", "check": check}], "retrieved": world, "steps": 1,
            "ms": round((time.perf_counter() - t0) * 1000, 2)}


_TOKEN = re.compile(r"-?\d+(?:\.\d+)?|[A-Za-z]+_[A-Za-z_]+|[A-Z]{2,}[0-9-]*[A-Z0-9]*|[A-Z]+\d+")


def _keys(obj, out: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _grounded(item: str, haystack: str, keys: set[str]) -> bool:
    """True when the statement quotes something a tool returned: a number,
    an id, or the name of a field the tool's answer actually contained."""
    if any(re.search(r"\b" + re.escape(k) + r"\b", item) for k in keys if len(k) >= 4):
        return True
    tokens = [t for t in _TOKEN.findall(item) if len(t) >= 2]
    if not tokens:
        return False
    for t in tokens:
        if t in haystack:
            return True
        if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
            try:
                v = float(t)
            except ValueError:
                continue
            # Allow rounding: "1800 ms" for 1800.0, "45%" for 0.45, "451,880" written without the comma.
            for cand in {f"{v:.0f}", f"{v:.1f}", f"{v / 100:.2f}", f"{v / 100:g}", f"{v:g}"}:
                if cand in haystack:
                    return True
    return False


def grade(run: dict, label: dict) -> dict:
    r = run["result"]
    retrieved = run.get("retrieved", {})
    haystack = json.dumps(retrieved, default=str).replace(",", "")
    keys = _keys(retrieved, set())
    grounded = [_grounded(e.replace(",", ""), haystack, keys) for e in r["evidence"]]
    harmful = (label["category"] in ("genuine_move", "venue_halt") and r["proposed_action"] not in ("no_action", "escalate_to_human")) or \
              (label["category"] in ("bad_print", "crossed_book", "duplicate_resend", "schema_drift", "clock_skew")
               and r["proposed_action"] == "no_action") or \
              (label["category"] == "unknown" and r["proposed_action"] not in ("escalate_to_human", "no_action"))
    category_ok = r["category"] == label["category"]
    action_ok = r["proposed_action"] == label["action"]
    return {
        "category_ok": category_ok, "action_ok": action_ok,
        "grounded": sum(grounded), "evidence": len(grounded), "all_grounded": all(grounded),
        "harmful": bool(harmful), "abstained": r["proposed_action"] == "escalate_to_human",
        "passed": category_ok and action_ok and all(grounded) and not harmful,
    }

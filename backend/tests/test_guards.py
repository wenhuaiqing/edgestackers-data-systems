"""The query validator, the triage grader, and the agent's tool loop."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.app.services import sql_validator, triage


@pytest.mark.parametrize("sql", [
    "SELECT * FROM bars",
    "WITH x AS (SELECT * FROM bars) SELECT * FROM x",
    "select count(*) from trades where status = 'held' limit 10",
])
def test_validator_allows_reads(sql):
    assert sql_validator.validate(sql).ok


@pytest.mark.parametrize("sql", [
    "DELETE FROM bars",
    "SELECT * FROM bars; DROP TABLE bars",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM audit_log",
    "SELECT * FROM kv",
    "ATTACH 'x.db' AS x",
    "SELECT getenv('LLM_API_KEY')",
])
def test_validator_refuses(sql):
    assert not sql_validator.validate(sql).ok


def test_validator_caps_the_limit():
    v = sql_validator.validate("SELECT * FROM trades LIMIT 999999")
    assert v.ok and v.sql.endswith(f"LIMIT {sql_validator.MAX_LIMIT}")


def _run(category, action, evidence, retrieved):
    return {"result": {"category": category, "proposed_action": action, "evidence": evidence, "confidence": 0.9,
                       "affects_trading": True, "instruments_to_gate": [], "summary": ""}, "retrieved": retrieved}


def test_grader_rejects_ungrounded_evidence():
    world = {"get_price_context": {"five_minute_median_before": 4.4, "by_venue": {"PRIMARY": {"max_deviation": 9.0}}}}
    ok = triage.grade(_run("bad_print", "hold_and_await_cancel", ["median 4.4 before the print"], world),
                      {"category": "bad_print", "action": "hold_and_await_cancel"})
    assert ok["passed"]
    made_up = triage.grade(_run("bad_print", "hold_and_await_cancel", ["ALT printed at 52.17"], world),
                           {"category": "bad_print", "action": "hold_and_await_cancel"})
    assert not made_up["all_grounded"] and not made_up["passed"]


def test_grader_accepts_a_quoted_field_name():
    world = {"get_contract_diff": {"conforms": False, "missing_required": ["qty"]}}
    g = triage.grade(_run("schema_drift", "propose_contract_version", ["conforms: false"], world),
                     {"category": "schema_drift", "action": "propose_contract_version"})
    assert g["all_grounded"]


def test_blocking_a_genuine_move_is_harmful():
    g = triage.grade(_run("bad_print", "hold_and_await_cancel", ["4.4"], {"x": 4.4}),
                     {"category": "genuine_move", "action": "no_action"})
    assert g["harmful"] and not g["passed"]


@pytest.mark.needs_build
def test_the_runbook_fails_every_hard_case(fresh_db):
    from src.app.services.triage_cases import build_cases
    cases = [c for c in build_cases(fresh_db.rows("SELECT * FROM alerts")) if c["kind"] == "hard"]
    assert len(cases) == 6
    for c in cases:
        assert not triage.grade(triage.run_rules(c["alert"]), c["label"])["passed"], c["case_id"]


def test_tool_loop_echoes_provider_metadata(monkeypatch):
    """Gemini 3 attaches a thought signature to each tool call and refuses the
    next turn without it; the loop must send the message back as received."""
    sent = []

    class Msg:
        def __init__(self, calls):
            self.content = None
            self.tool_calls = calls

        def model_dump(self, exclude_none=True):
            return {"role": "assistant", "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments},
                 "extra_content": {"google": {"thought_signature": "sig-" + c.id}}} for c in self.tool_calls]}

    def call(name, args, id_):
        return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=json.dumps(args)))

    verdict = {"category": "bad_print", "confidence": 0.9, "evidence": ["median 4.4"], "proposed_action": "hold_and_await_cancel",
               "affects_trading": True, "instruments_to_gate": [], "summary": "s"}
    replies = iter([Msg([call("get_price_context", {}, "c1")]), Msg([call("submit_triage", verdict, "c2")])])

    def fake_call(fn):
        class C:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        sent.append(json.loads(json.dumps(kw["messages"], default=str)))
                        return SimpleNamespace(choices=[SimpleNamespace(message=next(replies))])
        return fn("m", C), "m"

    monkeypatch.setattr(triage.llm, "call", fake_call)
    out = triage.run_agent({"alert_id": "A", "summary": "price_band fired", "venue": "PRIMARY", "stream": "trades",
                            "day": "2026-10-14", "world": {"get_price_context": {"five_minute_median_before": 4.4}}})
    assert out["result"]["category"] == "bad_print"
    second_turn = sent[1]
    echoed = [m for m in second_turn if m.get("role") == "assistant"][0]
    assert echoed["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-c1"

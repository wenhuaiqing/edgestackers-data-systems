"""Governed writes through the API: token, separation of duties, decided
once, promotion by rule. And replay reproduces the recorded output."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.main import app

pytestmark = pytest.mark.needs_build

TOKEN = {"X-Write-Token": "test-token"}


@pytest.fixture()
def client(fresh_db):
    return TestClient(app)


def test_writes_need_the_token(client):
    r = client.post("/api/proposals/CV-0007/approve", json={"note": ""}, headers={"X-Actor": "Risk desk"})
    assert r.status_code == 401
    assert "read-only" in r.json()["detail"]


def test_the_proposer_cannot_approve(client, fresh_db):
    r = client.post("/api/proposals/CV-0007/approve", json={"note": ""}, headers={**TOKEN, "X-Actor": "triage-agent"})
    assert r.status_code == 403
    assert "cannot also decide" in r.json()["detail"]
    refused = fresh_db.rows("SELECT * FROM audit_log WHERE outcome = 'refused'")
    assert refused and refused[0]["actor"] == "triage-agent"


def test_approval_reprocesses_from_raw_and_is_decided_once(client, fresh_db):
    held = fresh_db.scalar("SELECT count(*) FROM quarantine WHERE check_id = 'schema'")
    assert held > 10_000
    r = client.post("/api/proposals/CV-0007/approve", json={"note": "checked the KS"}, headers={**TOKEN, "X-Actor": "Risk desk"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["after"]["held_by_schema"] == 0
    assert body["after"]["degraded_minutes"] < body["before"]["degraded_minutes"]
    assert fresh_db.scalar("SELECT status FROM incidents WHERE incident_id = 'INC-06'") == "resolved"
    again = client.post("/api/proposals/CV-0007/approve", json={"note": ""}, headers={**TOKEN, "X-Actor": "Someone else"})
    assert again.status_code == 409


def test_promotion_follows_the_rule(client, fresh_db):
    import json
    promotion = json.loads(fresh_db.kv("promotion"))
    r = client.post("/api/models/mr-v2/promote", headers={**TOKEN, "X-Actor": "Risk desk"})
    if promotion["eligible"]:
        assert r.status_code == 200
    else:
        assert r.status_code == 409
        assert "not met" in r.json()["detail"] or "Not promoted" in r.json()["detail"]


def test_replay_reproduces_every_partition(client):
    r = client.post("/api/replay", json={"day": "2026-10-14"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["all_match"], [p for p in body["partitions"] if not p["match"]]
    assert all(f["match"] for f in body["files"])


def test_every_read_endpoint_answers(client):
    for path in ["/api/meta", "/api/overview", "/api/feeds", "/api/pipeline", "/api/quality", "/api/incidents",
                 "/api/decisions", "/api/ablation", "/api/operations", "/api/triage",
                 "/api/bars?instrument=INS-013&day=2026-10-14",
                 "/api/lineage?instrument=INS-013&minute=2026-10-14T12:28:00"]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text[:200])


def test_triage_without_a_model_says_so(client):
    r = client.post("/api/triage/run", json={"alert_id": "ALR-05", "engine": "agent"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "rules" and "No language model" in body["fallback_reason"]

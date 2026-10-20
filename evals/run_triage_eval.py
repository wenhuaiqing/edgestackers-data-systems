"""Run the triage eval: every labelled case through the rules baseline and the
agent, graded the same way. Writes evals/status.json, which the Triage page
reads.

Usage (from backend/):
  uv run python ../evals/run_triage_eval.py            # agent + rules
  uv run python ../evals/run_triage_eval.py --rules    # rules only, no LLM
  uv run python ../evals/run_triage_eval.py --regrade  # re-grade the stored runs, no LLM
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from src.app.services import db, llm  # noqa: E402
from src.app.services.triage import grade, run_agent, run_rules  # noqa: E402
from src.app.services.triage_cases import build_cases  # noqa: E402
from src.settings import settings  # noqa: E402

OUT = REPO_ROOT / "evals" / "status.json"


def summarise(results: list[dict], engine: str) -> dict:
    rs = [r for r in results if r["engine"] == engine]
    ok = [r for r in rs if "grade" in r]
    if not rs:
        return {}
    by_kind = {}
    for kind in ("real", "variant", "hard"):
        k = [r for r in ok if r["kind"] == kind]
        by_kind[kind] = {"cases": len(k), "passed": sum(r["grade"]["passed"] for r in k)}
    ms = [r["ms"] for r in ok]
    return {
        "cases": len(rs), "errors": len(rs) - len(ok),
        "passed": sum(r["grade"]["passed"] for r in ok),
        "category_ok": sum(r["grade"]["category_ok"] for r in ok),
        "harmful": sum(r["grade"]["harmful"] for r in ok),
        "abstained": sum(r["grade"]["abstained"] for r in ok),
        "evidence_grounded": sum(r["grade"]["grounded"] for r in ok),
        "evidence_items": sum(r["grade"]["evidence"] for r in ok),
        "by_kind": by_kind,
        "p50_ms": round(statistics.median(ms)) if ms else None,
        "p95_ms": round(sorted(ms)[int(0.95 * (len(ms) - 1))]) if ms else None,
        "avg_steps": round(statistics.mean(r["steps"] for r in ok), 2) if ok else None,
        "fallback_model_used": sum(1 for r in ok if r.get("model") not in (settings.llm_chat_model, "runbook")),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", action="store_true", help="rules baseline only")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between agent cases (free-tier pacing)")
    parser.add_argument("--regrade", action="store_true", help="re-grade stored runs with the current grader")
    args = parser.parse_args()

    if args.regrade:
        status = json.loads(OUT.read_text(encoding="utf-8"))
        for r in status["results"]:
            if r.get("engine") == "agent" and r.get("retrieved") is not None:
                r["grade"] = grade({"result": r["result"], "retrieved": r["retrieved"]}, r["label"])
        status["summary"] = {"rules": summarise(status["results"], "rules"),
                             "agent": summarise(status["results"], "agent") if status["summary"].get("agent") else None}
        status["regraded_at"] = datetime.now().replace(microsecond=0).isoformat()
        OUT.write_text(json.dumps(status, indent=1, default=str), encoding="utf-8", newline="\n")
        print(json.dumps(status["summary"], indent=1))
        return 0

    cases = build_cases(db.rows("SELECT * FROM alerts ORDER BY alert_id"))
    results: list[dict] = []
    use_agent = not args.rules and llm.configured()
    started = datetime.now().replace(microsecond=0)
    for i, case in enumerate(cases, start=1):
        engines = [("rules", run_rules)] + ([("agent", run_agent)] if use_agent else [])
        for engine, fn in engines:
            entry = {"case_id": case["case_id"], "kind": case["kind"], "engine": engine, "label": case["label"],
                     "why": case.get("why"), "check_id": case["alert"]["check_id"], "summary": case["alert"]["summary"]}
            try:
                run = fn(case["alert"])
                entry.update({"result": run["result"], "model": run["model"], "ms": run["ms"], "steps": run["steps"],
                              "tools": [t["tool"] for t in run["trace"] if t.get("kind") == "tool"],
                              # Stored so a grader change can re-grade without new model calls.
                              "retrieved": run["retrieved"] if engine == "agent" else None,
                              "grade": grade(run, case["label"])})
            except Exception as exc:  # noqa: BLE001 - an error is a result, recorded as one
                entry.update({"error": f"{type(exc).__name__}: {str(exc)[:300]}", "ms": None, "steps": None})
            results.append(entry)
            if engine == "agent":
                g = entry.get("grade", {})
                print(f"[{i:02d}/{len(cases)}] {case['case_id']:32s} agent "
                      f"{'PASS' if g.get('passed') else 'FAIL' if g else 'ERROR'} "
                      f"{entry.get('result', {}).get('category', '-'):20s} {entry.get('ms')} ms", flush=True)
                time.sleep(args.pause)
    status = {
        "run_at": started.isoformat(), "finished_at": datetime.now().replace(microsecond=0).isoformat(),
        "model": settings.llm_chat_model if use_agent else None,
        "fallback_model": settings.llm_fallback_model if use_agent else None,
        "cases": len(cases),
        "summary": {"rules": summarise(results, "rules"), "agent": summarise(results, "agent") if use_agent else None},
        "results": results,
    }
    OUT.write_text(json.dumps(status, indent=1, default=str), encoding="utf-8", newline="\n")
    print(json.dumps(status["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# tapeline

Portfolio demo: a data-systems platform for a trading desk - raw multi-venue
market events through contracts, validation, quarantine, lineage and replay to
the orders a strategy sends, with every control priced by ablation and an AI
triage agent graded against the runbook. Built for an application to a
quantitative trading firm. **All market data is synthetic.**

## Layout

```
tapeline/
├── backend/           FastAPI + Python 3.12 (uv)
│   └── src/app/
│       ├── pipeline/  reference, generate, contracts, stages, decisions, ablation,
│       │              incidents, alerts, registry, persist (the build and reprocessing)
│       ├── services/  analytics (reads), workflow (governed writes), replay, triage,
│       │              triage_cases, llm, db, auth, rate_limit, sql_validator, timings
│       └── routers/   pages (reads), workflow (token-gated), actions (replay, triage, query)
├── contracts/         one YAML data contract per feed and stream
├── scripts/           build_platform.py - the whole platform from nothing
├── evals/             run_triage_eval.py -> status.json (shown on the AI triage page)
├── frontend/          React 18 + Vite; pages/<Section>/<Page>.jsx auto-discovered
└── infra-azure/       Terraform; build.sha256 is the pinned manifest
```

## How to run

```powershell
cd backend; uv sync; uv run python ../scripts/build_platform.py; uv run uvicorn src.main:app --port 8041
cd frontend; npm install; npm run dev     # :5241
```

Tests: `cd backend && uv run pytest`. Pages: `cd frontend && BASE=http://localhost:5241 node evals/check-pages.mjs`.

## Conventions

- **No emojis in code or output.** Australian English; dates DD/MM/YYYY on screen;
  straight quotes and hyphens only (the page check fails on typographic ones).
- Timestamps are exchange-local (AEDT), stored naive, labelled on screen.
- Every defect the generator seeds is declared once in `pipeline/reference.py`;
  tests assert each is found from the data, never from the reference.
- Hold, never guess: a check that cannot decide holds the event and records why.
  Nothing is dropped without a quarantine row.
- Decisions read bars as first published, never restated.
- Every write is token-gated, audit-logged, and refused - not warned - when the
  rule says no. The proposer of a change cannot approve it.
- Numbers on screen come from the data. The triage agent proposes; it cannot write.
- Changing the generator, pipeline or decisions changes the output: rebuild with
  `--write-manifest` and commit `infra-azure/build.sha256`, or the image build fails.
- Never name the firm the demo was built for in the product's own chrome; the
  First 90 days page addresses them, nothing else does.

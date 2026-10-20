# Edge Stackers - data systems platform

**Raw market events to decisions you can trust.** A working data-systems
platform: three market feeds with the defects real feeds have, taken through
contracts, validation, quarantine, lineage and replay to the orders a
short-horizon strategy sends - with every control priced by switching it off,
and an AI triage agent measured against the on-call runbook.

> **Built for a job application to Edge Stackers. Not affiliated with or
> endorsed by Edge Stackers.** **All market data is synthetic.** The venues, instruments, prices and the
> strategy are invented and generated from a seed by
> `backend/src/app/pipeline/generate.py`. Instrument codes are four letters so
> nothing on screen can be mistaken for a real security.

## What it shows

| | |
|---|---|
| **Feeds** | PRIMARY and ALT direct feeds (trades and top-of-book quotes) and a vendor's redundant copy of PRIMARY in the vendor's own shape. Five sessions, 617,264 events, 30 raw files hashed on landing. |
| **Contracts** | Six YAML contracts naming their consumers (Execution, Research, Risk) and SLAs. A partition that breaks its contract is quarantined whole; a change is a new version, proposed with evidence and approved by someone other than the proposer. |
| **Pipeline** | Twelve timed stages: land, contract, canonical, clock, symbols, dedupe, arbitrate, band, cancels, bars, book, gate. Each day is independent, so any session replays from its files alone and is proved identical by partition digests. |
| **Defects, all found from the data** | A duplicate burst after a reconnect; two PRIMARY gaps filled from the vendor; the vendor's clock 1.8 s fast; a decimal-shift print cancelled by the exchange; a genuine 9% move the band must release; an unannounced schema change; a crossed book; a symbol change with a late symbol master. |
| **Decisions** | A plain mean-reversion strategy on one-minute bars, trading through a quality gate (block or half size), on bars as first published (never restated), under a A$20,000 desk loss limit. A shadow model beside it; promotion only by a rule agreed in advance. |
| **What controls are worth** | Every control switched off in turn and the week re-run from raw. With the price band off, one print marks the desk down A$451,880, trips the loss limit and stops trading for the afternoon. Some controls changed nothing this week; both are reported. |
| **AI triage** | A tool-calling agent (nine tools over a snapshot frozen when the alert fired) that submits a typed verdict. Graded against the runbook on 33 labelled cases, six of them built to trip a runbook; failures listed one by one. It proposes; it cannot write. |

## Pages

Desk view · Feeds & contracts · Pipeline & lineage · Checks & quarantine ·
Replay & recovery · Query layer · Decisions & models · What controls are worth ·
Incidents · AI triage · Operations · First 90 days.

## Architecture

```
  raw/ PRIMARY  ALT  VENDOR  REF          scripts/build_platform.py (in the image build)
        │ parquet per feed, stream, day    generate -> pipeline -> decisions -> ablation
        ▼                                  -> incidents, alerts -> verify against
  ┌──────────── pipeline (per day) ─────────────┐   infra-azure/build.sha256
  │ land · contract · canonical · clock ·       │
  │ symbols · dedupe · arbitrate · band ·       │──► quarantine (every hold, with reason,
  │ cancels · bars (published + final) · book · │    raw file and row, resolution)
  │ gate                                        │──► partition digests (the replay contract)
  └──────────────┬──────────────────────────────┘
                 ▼
  decisions: live + shadow model ─ gate ─ loss limit ─► orders, equity, P&L
                 ▼
  DuckDB (one file) ◄── FastAPI ◄── nginx ◄── React SPA
     ▲                     │
     │ approvals reprocess │ triage agent ──► Gemini (OpenAI protocol), fallback model,
     └─ from raw ──────────┘                  runbook when both are down - said on screen
```

Live deployment: Azure Container Apps (one app, nginx and FastAPI as two
containers), a private registry pulled with a managed identity, Key Vault for
the model key and the write token, scale to zero. Terraform in `infra-azure/`.
There is no database server or blob store: the data is built inside the image
and verified, so the image is the artefact.

## Run it

```powershell
cd backend
uv sync
uv run python ../scripts/build_platform.py        # about 90 s; verifies against the pinned manifest
cp ../.env.example ../.env                          # model key optional; DEMO_WRITE_TOKEN for approvals
uv run uvicorn src.main:app --port 8041

cd ../frontend
npm install
npm run dev                                         # http://localhost:5241
```

Open `http://localhost:5241/?write_token=<DEMO_WRITE_TOKEN>` once to unlock
approvals in that browser session. The plain link is read-only, and the server
says why it refuses.

## Checks

```powershell
cd backend;  uv run pytest                                   # pipeline, decisions, workflow, guards
cd frontend; $env:BASE="http://localhost:5241"; node evals/check-pages.mjs
cd backend;  uv run python ../evals/run_triage_eval.py        # agent + runbook, graded; writes evals/status.json
cd backend;  uv run python ../evals/run_triage_eval.py --regrade
```

Changing the generator, the pipeline or the decisions changes the output:
rebuild with `--write-manifest` and commit `infra-azure/build.sha256`.

## Deploy

```powershell
cd infra-azure
cp terraform.tfvars.example terraform.tfvars        # subscription, alert e-mail, model key (gitignored)
terraform init
terraform apply -target azurerm_container_registry.main -target azurerm_role_assignment.acr_push_self
$acr = terraform output -raw acr_login_server
az acr login --name $acr.Split('.')[0]
$sha = git rev-parse --short HEAD
docker build -f ../backend/Dockerfile --build-arg GIT_SHA=$sha -t "$acr/edgestackers/backend:$sha" ..
docker build -f ../frontend/Dockerfile -t "$acr/edgestackers/frontend:$sha" ..
docker push "$acr/edgestackers/backend:$sha"; docker push "$acr/edgestackers/frontend:$sha"
terraform apply -var "image_tag=$sha"
```

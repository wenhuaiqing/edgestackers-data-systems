// Running it: latency measured on this replica, what each run cost, how it
// is built and deployed, what is tested, and every write anyone made.

import { useState } from "react";
import { RotateCcw } from "lucide-react";
import { useTheme } from "../../context/ThemeContext.jsx";
import { apiWrite, fmtAud, fmtDateTime, fmtDuration, fmtInt, fmtMs, useApi } from "../../lib/api.js";
import {
  Badge, Button, Callout, Card, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader, SectionTitle, Stat, Table,
} from "../../lib/ui.jsx";

const TESTS = [
  ["Generator", "same seed, same bytes; every seeded defect present"],
  ["Contracts", "a renamed field quarantines the partition; v2 accepts it; unknown fields refuse"],
  ["Pipeline", "dedupe is idempotent; arbitration fills by trade id; the bad print never reaches a bar; a confirmed move is released; the clock offset is applied only inside tolerance; a symbol change keeps one instrument"],
  ["Replay", "a session replayed from raw reproduces every partition digest"],
  ["Decisions", "decisions never read a restated bar; the loss limit flattens and stops the desk"],
  ["Workflow", "the proposer cannot approve; a proposal is decided once; promotion refuses when the rule fails; writes need the token"],
  ["Query layer", "SELECT only; allowlisted tables; file and URL functions refused"],
  ["Triage", "the grader rejects ungrounded evidence and harmful actions; the runbook fails every hard case; the tool loop echoes provider metadata"],
  ["Pages", "every page renders in Edge at desktop and phone width: no console errors, no failed calls, no unformatted values, no page wider than the phone"],
];

export default function Operations() {
  const { t } = useTheme();
  const { data, error, reload } = useApi("/api/operations");
  const { data: meta } = useApi("/api/meta");
  const [msg, setMsg] = useState(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const build = data.runs.find((r) => r.kind === "full build");

  const reset = async () => {
    try {
      await apiWrite("/api/reset");
      setMsg({ tone: "good", text: "Restored the built state. Every approval and promotion is undone." });
      reload();
    } catch (e) {
      setMsg({ tone: "critical", text: e.message });
    }
  };

  return (
    <>
      <PageHeader
        title="Operations"
        brief="Use cloud infrastructure, infrastructure as code, testing and CI/CD to make environments reproducible and releases safe."
        subtitle="Latency is measured on this replica since it started. Cost is the compute each run used at list price. The environment is Terraform; the data is rebuilt from code and a seed and checked against pinned digests before the image is accepted."
        right={<Button icon={RotateCcw} onClick={reset}>Reset the demo</Button>}
      />
      {msg && <Callout tone={msg.tone}>{msg.text}</Callout>}
      <Grid cols={4} min={200}>
        <Stat label="Build" value={fmtDuration(Number(data.build_seconds))} sub="generate, run, ablate, verify - from nothing" emphasis />
        <Stat label="Governed run" value={build ? fmtMs(build.wall_ms) : "-"} sub={build ? `${fmtAud(build.cost_aud, { decimals: 5 })} of compute at list price` : ""} />
        <Stat label="Replica up" value={meta ? fmtDuration(meta.uptime_seconds) : "-"} sub={meta ? `version ${meta.version}` : ""} />
        <Stat label="Writes recorded" value={fmtInt(data.audit.length)} sub="approvals, refusals, promotions, resets" />
      </Grid>

      <Grid cols={2} min={460}>
        <Card title="API latency on this replica" hint="In memory, last 5,000 calls; resets when the replica scales to zero. Refused writes count as refused, not as errors.">
          <Table
            maxHeight={380}
            columns={[
              { key: "path", label: "Route", render: (r) => <Mono>{r.path}</Mono> },
              { key: "calls", label: "Calls", align: "right", render: (r) => fmtInt(r.calls) },
              { key: "p50_ms", label: "p50", align: "right", render: (r) => fmtMs(r.p50_ms) },
              { key: "p95_ms", label: "p95", align: "right", render: (r) => fmtMs(r.p95_ms) },
              { key: "refused", label: "Refused", align: "right", render: (r) => fmtInt(r.refused) },
              { key: "errors", label: "Errors", align: "right", render: (r) => r.errors ? <Badge tone="critical">{r.errors}</Badge> : "0" },
            ]}
            rows={data.timings}
            empty="No calls yet on this replica."
          />
        </Card>
        <Card title="Where it runs">
          <KeyValues items={[
            ["Compute", "Azure Container Apps, consumption plan, one app with two containers: nginx (SPA, proxy, security headers) and FastAPI"],
            ["Scale", "to zero when idle; a 30-60 s cold start is the accepted trade for a link opened a few times"],
            ["Data", "rebuilt in the image build from code and a seed; the build fails if any digest differs from the pinned manifest"],
            ["Secrets", "Key Vault, read by the app's managed identity; no key in the image or the repository"],
            ["Images", "a private registry pulled with the same identity - no registry password exists"],
            ["Infrastructure", "Terraform in infra-azure/; a monthly budget alert"],
            ["Model", meta?.llm_configured ? `${meta.llm_model} over the OpenAI protocol, with a second free-tier model as fallback` : "none configured - the runbook answers"],
          ]} />
        </Card>
      </Grid>

      <SectionTitle>Tested</SectionTitle>
      <Card hint="cd backend && uv run pytest; node frontend/evals/check-pages.mjs; uv run python ../evals/run_triage_eval.py">
        <Table columns={[{ key: 0, label: "Area", render: (r) => <b>{r[0]}</b> }, { key: 1, label: "What is asserted", wrap: true, render: (r) => r[1] }]} rows={TESTS} />
      </Card>

      <Grid cols={2} min={460}>
        <Card title="Pipeline stages, every run">
          <Table
            maxHeight={360}
            columns={[
              { key: "run_id", label: "Run", render: (r) => <Mono>{r.run_id}</Mono> },
              { key: "stage", label: "Stage" },
              { key: "rows_out", label: "Rows out", align: "right", render: (r) => fmtInt(r.rows_out) },
              { key: "wall_ms", label: "Wall", align: "right", render: (r) => fmtMs(r.wall_ms) },
              { key: "cpu_ms", label: "CPU", align: "right", render: (r) => fmtMs(r.cpu_ms) },
            ]}
            rows={data.stages}
          />
        </Card>
        <Card title="Audit log" hint="Every write and every refusal, with who asked and why it was refused.">
          <Table
            maxHeight={360}
            columns={[
              { key: "ts", label: "When", render: (r) => fmtDateTime(r.ts) },
              { key: "actor", label: "Who" },
              { key: "action", label: "Action" },
              { key: "subject", label: "On" },
              { key: "outcome", label: "Outcome", render: (r) => <Badge tone={r.outcome === "done" ? "good" : "critical"}>{r.outcome}</Badge> },
              { key: "detail", label: "Detail", wrap: true, render: (r) => (r.detail || "").slice(0, 160) },
            ]}
            rows={data.audit}
            empty="No writes yet. Approve or refuse something on Feeds & contracts."
          />
        </Card>
      </Grid>
    </>
  );
}

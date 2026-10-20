// The triage agent, measured: a graded eval against the runbook it has to
// beat, its failures listed rather than averaged away, and a live run on any
// of the week's alerts with every tool call shown.

import { useMemo, useState } from "react";
import { Bot, BookOpen } from "lucide-react";
import { useLocation } from "react-router-dom";
import { useTheme } from "../../context/ThemeContext.jsx";
import { ACTION_LABEL, CATEGORY_LABEL, api, fmtDateTime, fmtMs, useApi } from "../../lib/api.js";
import {
  Badge, Button, CTAButton, Callout, Card, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader, SectionTitle,
  Select, Stat, Table,
} from "../../lib/ui.jsx";

function failureReason(g) {
  if (!g) return "error";
  if (g.harmful) return "harmful action";
  if (!g.category_ok) return "wrong category";
  if (!g.action_ok) return "wrong action";
  if (!g.all_grounded) return "ungrounded evidence";
  return "";
}

function Verdict({ r, label }) {
  const { t } = useTheme();
  if (!r) return null;
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        <Badge tone={label && r.category === label.category ? "good" : "critical"}>{CATEGORY_LABEL[r.category]}</Badge>
        <Badge tone={label && r.proposed_action === label.action ? "good" : "critical"}>{ACTION_LABEL[r.proposed_action]}</Badge>
        <Badge tone="neutral">confidence {Math.round(r.confidence * 100)}%</Badge>
        {r.affects_trading && <Badge tone="warning">affects trading</Badge>}
      </div>
      <p style={{ fontSize: 13, margin: "0 0 8px", lineHeight: 1.5 }}>{r.summary}</p>
      <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, lineHeight: 1.55, color: t.textMuted }}>
        {r.evidence.map((e, i) => <li key={i}>{e}</li>)}
      </ul>
    </div>
  );
}

function LiveRun({ alerts, initial }) {
  const { t } = useTheme();
  const [alertId, setAlertId] = useState(initial || alerts[0]?.alert_id);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState(null);
  const [err, setErr] = useState(null);
  const alert = alerts.find((a) => a.alert_id === alertId);

  const go = async (engine) => {
    setBusy(true);
    setErr(null);
    setRun(null);
    try {
      setRun(await api("/api/triage/run", { method: "POST", body: { alert_id: alertId, engine } }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Triage one of the week's alerts" right={
      <Select label="Alert" value={alertId} onChange={(v) => { setAlertId(v); setRun(null); }}
              options={alerts.map((a) => ({ value: a.alert_id, label: `${a.alert_id}: ${a.summary.slice(0, 60)}` }))} />
    } hint="The agent chooses which tools to call; each answers from the snapshot frozen when the alert fired, so the run can be graded against the label.">
      {alert && (
        <KeyValues columns={3} items={[
          ["Alert", <Mono>{alert.alert_id}</Mono>],
          ["Raised", fmtDateTime(alert.raised_at, { ms: true })],
          ["Check", alert.check_id],
          ["Summary", alert.summary],
          ["Labelled", `${CATEGORY_LABEL[alert.label.category]}: ${ACTION_LABEL[alert.label.action]}`],
          ["Snapshot", `${Object.keys(alert.world).length} tools, frozen at the alert`],
        ]} />
      )}
      <div style={{ display: "flex", gap: 10, margin: "14px 0 6px", flexWrap: "wrap" }}>
        <CTAButton icon={Bot} onClick={() => go("agent")} disabled={busy}>{busy ? "Investigating..." : "Run the agent"}</CTAButton>
        <Button icon={BookOpen} onClick={() => go("rules")} disabled={busy}>Run the runbook</Button>
      </div>
      {err && <Callout tone="critical" title="Refused">{err.message}</Callout>}
      {run && (
        <div style={{ marginTop: 10 }}>
          {run.fallback_reason && <Callout tone="warning" title="Degraded, and saying so">{run.fallback_reason}</Callout>}
          <Grid cols={2} min={340}>
            <div>
              <SectionTitle>Steps ({run.engine}, {run.model}, {fmtMs(run.ms)})</SectionTitle>
              <ol style={{ margin: 0, paddingLeft: 20, fontSize: 12.5, lineHeight: 1.7 }}>
                {run.trace.map((s, i) => (
                  <li key={i}>
                    {s.kind === "tool" && <>called <Mono>{s.tool}</Mono></>}
                    {s.kind === "submit" && <b>submitted a verdict</b>}
                    {s.kind === "rule" && <>matched the runbook entry for <Mono>{s.check}</Mono></>}
                    {s.kind === "invalid_submit" && <span style={{ color: t.status.critical }}>submitted an invalid verdict and was told why</span>}
                    {s.kind === "text" && <span style={{ color: t.textMuted }}>replied without a tool call and was reminded</span>}
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <SectionTitle right={<Badge tone={run.grade.passed ? "good" : "critical"}>{run.grade.passed ? "passes" : failureReason(run.grade)}</Badge>}>Verdict</SectionTitle>
              <Verdict r={run.result} label={run.label} />
              <p style={{ fontSize: 12, color: t.textMuted, margin: "10px 0 0" }}>
                Evidence grounded: {run.grade.grounded} of {run.grade.evidence}. {run.grade.harmful ? "Harmful: this action would block a genuine move or let bad data through." : ""}
              </p>
            </div>
          </Grid>
        </div>
      )}
    </Card>
  );
}

export default function Triage() {
  const { t } = useTheme();
  const location = useLocation();
  const initial = new URLSearchParams(location.search).get("alert");
  const { data, error } = useApi("/api/triage");
  const [engine, setEngine] = useState("agent");

  const cases = useMemo(() => {
    if (!data?.eval) return [];
    const by = {};
    for (const r of data.eval.results) {
      by[r.case_id] ??= { case_id: r.case_id, kind: r.kind, label: r.label, why: r.why, summary: r.summary };
      by[r.case_id][r.engine] = r;
    }
    return Object.values(by);
  }, [data]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const ev = data.eval;
  const a = ev?.summary?.agent;
  const r = ev?.summary?.rules;
  const failures = cases.filter((c) => c[engine] && !(c[engine].grade?.passed));
  const hard = cases.filter((c) => c.kind === "hard");

  return (
    <>
      <PageHeader
        title="AI triage"
        brief="Build and operate practical AI and agentic workflows where they solve a real problem. Measure outputs and make failure modes visible."
        subtitle="When a check fires, someone has to work out what it means before anyone acts. The agent does that first pass: it chooses which of nine tools to call, reads what they return, and submits a typed verdict - a category, an action, and evidence that must quote what the tools said. It proposes; it cannot change anything. It is graded against the on-call runbook on the same cases, including six built to separate reasoning from matching the check's name."
      />

      {ev ? (
        <>
          <Grid cols={4} min={200}>
            <Stat label="Agent passes" value={`${a?.passed ?? "-"} / ${a?.cases ?? "-"}`} sub={`${ev.model}; ${a?.errors || 0} error(s)`} emphasis />
            <Stat label="Runbook passes" value={`${r?.passed} / ${r?.cases}`} sub="the check that fired decides" />
            <Stat label="Hard cases" value={`${a?.by_kind?.hard?.passed ?? "-"} vs ${r?.by_kind?.hard?.passed}`} sub={`agent vs runbook, of ${r?.by_kind?.hard?.cases}`} tone={a && a.by_kind.hard.passed < a.by_kind.hard.cases ? "warning" : undefined} />
            <Stat label="Harmful verdicts" value={`${a?.harmful ?? "-"} vs ${r?.harmful}`} sub="would block a real move or pass bad data" tone="critical" />
          </Grid>
          <Grid cols={4} min={200}>
            <Stat label="Evidence grounded" value={a ? `${a.evidence_grounded} / ${a.evidence_items}` : "-"} sub="statements quoting a value a tool returned" />
            <Stat label="Latency" value={a ? `${fmtMs(a.p50_ms)} p50` : "-"} sub={a ? `${fmtMs(a.p95_ms)} p95; ${a.avg_steps} steps on average` : ""} />
            <Stat label="Fallback model used" value={a ? a.fallback_model_used : "-"} sub={`${ev.fallback_model || "none"} when the primary shed load`} />
            <Stat label="Abstained" value={a ? a.abstained : "-"} sub="escalated to a person" />
          </Grid>
          {a && (
            <Callout tone="ai" title="What the numbers say">
              On the {a.by_kind.real.cases + a.by_kind.variant.cases} cases the runbook was written for, the runbook
              passes {r.by_kind.real.passed + r.by_kind.variant.passed} in under a millisecond and the agent passes{" "}
              {a.by_kind.real.passed + a.by_kind.variant.passed} in about {fmtMs(a.p50_ms)} - there the agent adds
              nothing but cost. It earns its place only on the hard cases, where the check's name points at the wrong
              cause: {a.by_kind.hard.passed} of {a.by_kind.hard.cases} against the runbook's {r.by_kind.hard.passed}.
              Better than the runbook; nowhere near good enough to act unsupervised, which is why it cannot. The model
              is not deterministic, so which hard cases it passes moves between runs. Last full run {fmtDateTime(ev.run_at)}.
            </Callout>
          )}
        </>
      ) : <Callout tone="warning">No eval has been run on this build.</Callout>}

      <LiveRun alerts={data.alerts} initial={initial} />

      {ev && (
        <>
          <SectionTitle>The hard cases</SectionTitle>
          <Card>
            <Table
              columns={[
                { key: "case_id", label: "Case", render: (c) => <Mono>{c.case_id.replace("hard-", "")}</Mono> },
                { key: "why", label: "What makes it hard", wrap: true },
                { key: "label", label: "Right answer", render: (c) => CATEGORY_LABEL[c.label.category] },
                { key: "rules", label: "Runbook", render: (c) => <Badge tone={c.rules?.grade?.passed ? "good" : "critical"}>{CATEGORY_LABEL[c.rules?.result?.category] || "error"}</Badge> },
                { key: "agent", label: "Agent", render: (c) => c.agent ? <Badge tone={c.agent.grade?.passed ? "good" : "critical"}>{CATEGORY_LABEL[c.agent.result?.category] || "error"}</Badge> : "-" },
              ]}
              rows={hard}
            />
          </Card>

          <SectionTitle right={<Select label="Engine" value={engine} onChange={setEngine} options={[{ value: "agent", label: "Agent" }, { value: "rules", label: "Runbook" }]} />}>
            Every failure, not an average
          </SectionTitle>
          <Card>
            <Table
              columns={[
                { key: "case_id", label: "Case", render: (c) => <Mono>{c.case_id}</Mono> },
                { key: "reason", label: "Failed on", render: (c) => <Badge tone="critical">{failureReason(c[engine].grade)}</Badge> },
                { key: "said", label: "Said", render: (c) => c[engine].result ? `${CATEGORY_LABEL[c[engine].result.category]}: ${ACTION_LABEL[c[engine].result.proposed_action]}` : c[engine].error },
                { key: "right", label: "Right answer", render: (c) => `${CATEGORY_LABEL[c.label.category]}: ${ACTION_LABEL[c.label.action]}` },
                { key: "tools", label: "Tools called", wrap: true, render: (c) => (c[engine].tools || []).join(", ") || "-" },
              ]}
              rows={failures}
              empty="No failures."
            />
          </Card>
        </>
      )}

      <SectionTitle>What the agent may and may not do</SectionTitle>
      <Card>
        <KeyValues items={[
          ["May", "Read the alert's frozen snapshot through nine tools; propose a category, an action and the instruments to gate."],
          ["May not", "Write anything. A proposal it makes - such as ALT's contract v2 - waits for a person, and the person cannot be the agent."],
          ["Budget", "Five steps; the last is forced to submit. 30 s per model call; a timeout is not retried."],
          ["When the model is down", "The runbook answers, and the page says so. Nothing degrades silently."],
          ["Abuse", "Eight runs per address and sixty in all per five minutes; the operator is exempt."],
          ["Recent live runs", data.recent.length ? data.recent.map((x) => `${x.alert_id} (${x.engine})`).slice(0, 6).join(", ") : "none yet on this replica"],
        ]} />
      </Card>
    </>
  );
}

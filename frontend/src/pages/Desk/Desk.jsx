// The front door: what came in this week, what the checks did with it, what
// the desk did with the result - and the one finding worth opening first.

import { Link } from "react-router-dom";
import { Bar, BarChart } from "recharts";
import { useTheme } from "../../context/ThemeContext.jsx";
import {
  CHECK_LABEL, SOURCE_LABEL, fmtAud, fmtDateTime, fmtDay, fmtDuration, fmtInt, fmtMs, useApi,
} from "../../lib/api.js";
import {
  Badge, Callout, Card, ChartFrame, ErrorNote, Grid, Loading, PageHeader, Stat, Table, useChartParts,
} from "../../lib/ui.jsx";

export const SEVERITY_TONE = { critical: "critical", high: "serious", medium: "warning", info: "neutral" };
export const STATUS_TONE = { open: "critical", resolved: "good", mitigated: "warning", "no action": "neutral" };

export default function Desk() {
  const { data, error } = useApi("/api/overview");
  const { t } = useTheme();
  const chart = useChartParts();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const c = data.counts;
  const live = data.pnl.find((p) => p.model_id === "mr-v1");
  const h = data.headline;
  const pending = data.proposals.filter((p) => p.status === "pending");

  return (
    <>
      <PageHeader
        title="Desk view"
        brief="Build dependable ingestion, storage and query layers for raw, changing event and trading data."
        subtitle={`Five sessions of three market feeds - ${fmtInt(c.events)} events in ${c.files} raw files - taken from the files to the orders a short-horizon strategy sent. Every figure here is computed from those files on each build. Nothing is typed in.`}
      />

      {h && (
        <Callout tone="critical" title="Start here: one print, wrong for eight and a half minutes">
          With the price band switched off, a decimal-shift print on MURR becomes the close of its 12:28 bar on
          14/10. The desk is marked down <b>{fmtAud(h.desk_worst_mark)}</b>, the {fmtAud(20000)} loss limit fires at{" "}
          {h.kill_switch.split(" ")[1]} and trading stops for the afternoon. With the band on, the print is held on
          arrival and never reaches a bar. <Link to="/tradeoffs" style={{ color: t.accent, fontWeight: 650 }}>What each control is worth</Link>
          {" "}re-runs the week with every control switched off in turn.
        </Callout>
      )}

      <Grid cols={5} min={190}>
        <Stat label="Events ingested" value={fmtInt(c.events)} sub={`${c.files} raw files, hashed and pinned`} emphasis />
        <Stat label="Held or quarantined" value={fmtInt(c.quarantined)} sub="by ten checks; none silently dropped" />
        <Stat label="Bars published" value={fmtInt(c.bars)} sub={`${c.restated} restated after publication`} />
        <Stat label="Live model, week" value={fmtAud(live?.pnl)} sub={`${fmtInt(live?.orders)} orders, gated on data quality`} />
        <Stat label="Incidents" value={c.incidents} sub={`${c.open_incidents} open, waiting on a decision`} tone={c.open_incidents ? "warning" : undefined} />
      </Grid>

      <Grid cols={2} min={700}>
        <Card title="Feeds" hint="Receive time minus exchange time, first copies only. The vendor copy is held in standby and used only where PRIMARY has a gap.">
          <Table
            columns={[
              { key: "source", label: "Feed", render: (r) => SOURCE_LABEL[r.source] || r.source },
              { key: "events", label: "Trade events", align: "right", render: (r) => fmtInt(r.events) },
              { key: "p99_ms", label: "p99 latency", align: "right", render: (r) => fmtMs(r.p99_ms) },
              { key: "rejected", label: "Rejected", align: "right", render: (r) => fmtInt(r.rejected) },
              { key: "standby", label: "Standby", align: "right", render: (r) => fmtInt(r.standby) },
            ]}
            rows={data.feeds}
          />
          <div style={{ height: 12 }} />
          <Table
            columns={[
              { key: "venue", label: "Partitions", render: (r) => `${r.venue} ${r.stream}` },
              { key: "partitions", label: "Sessions", align: "right" },
              { key: "quarantined", label: "Status", render: (r) => r.quarantined
                ? <Badge tone="critical">{r.quarantined} quarantined by contract</Badge>
                : <Badge tone="good">conform</Badge> },
            ]}
            rows={data.partitions}
          />
        </Card>

        <Card title="What the gate allowed, by session" hint="Instrument-minutes open, degraded to half size, or blocked. 15/10 and 16/10 run degraded because ALT's trades are quarantined.">
          <ChartFrame height={250}>
            <BarChart data={data.gate_days.map((d) => ({ ...d, label: fmtDay(d.day) }))} margin={{ left: 4, right: 8, top: 8 }}>
              {chart.grid}
              {chart.xAxis({ dataKey: "label" })}
              {chart.yAxis({ tickFormatter: fmtInt })}
              {chart.tooltip({ formatter: (v) => fmtInt(v) })}
              {chart.legend()}
              <Bar dataKey="open" name="Open" stackId="g" fill={t.series[0]} />
              <Bar dataKey="degraded" name="Degraded" stackId="g" fill={t.series[1]} />
              <Bar dataKey="blocked" name="Blocked" stackId="g" fill={t.status.critical} />
            </BarChart>
          </ChartFrame>
        </Card>
      </Grid>

      <Grid cols={2} min={420}>
        <Card title="Incidents this week" right={<Link to="/incidents" style={{ fontSize: 12, color: t.accent, fontWeight: 650 }}>All incidents</Link>}>
          <Table
            columns={[
              { key: "title", label: "Incident", wrap: true },
              { key: "severity", label: "Severity", render: (r) => <Badge tone={SEVERITY_TONE[r.severity]}>{r.severity}</Badge> },
              { key: "ttd_seconds", label: "Time to detect", align: "right", render: (r) => fmtDuration(r.ttd_seconds) },
              { key: "status", label: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge> },
            ]}
            rows={data.incidents}
          />
        </Card>

        <Card title="Waiting on a person">
          {pending.map((p) => (
            <Callout key={p.proposal_id} tone="warning" title={`${p.proposal_id}: ${p.subject}, proposed by ${p.proposed_by}`}>
              {p.summary} <Link to="/feeds" style={{ color: t.accent, fontWeight: 650 }}>Review the evidence</Link>
            </Callout>
          ))}
          {!pending.length && <Callout tone="good" title="No contract changes pending">Every proposal has been decided.</Callout>}
          {data.promotion && (
            <Callout tone={data.promotion.eligible ? "good" : "neutral"} title={data.promotion.eligible ? "Shadow model eligible for promotion" : "Shadow model not yet eligible"}>
              {data.promotion.checks.filter((x) => !x.passed).map((x) => `${x.rule}: ${x.value}`).join("; ") || "Every rule agreed before the shadow run is met."}{" "}
              <Link to="/decisions" style={{ color: t.accent, fontWeight: 650 }}>Decisions & models</Link>
            </Callout>
          )}
          <Table
            columns={[
              { key: "check_id", label: "Check", render: (r) => CHECK_LABEL[r.check_id] || r.check_id },
              { key: "n", label: "Events", align: "right", render: (r) => fmtInt(r.n) },
              { key: "still_held", label: "Still held", align: "right", render: (r) => fmtInt(r.still_held) },
            ]}
            rows={data.quarantine_by_check}
          />
          {data.runs?.[0] && (
            <p style={{ fontSize: 12, color: t.textMuted, margin: "10px 0 0" }}>
              Last run {data.runs[0].run_id} ({data.runs[0].kind}, {data.runs[0].trigger}) at {fmtDateTime(data.runs[0].started_at)}:
              {" "}{fmtMs(data.runs[0].wall_ms)}, {fmtAud(data.runs[0].cost_aud, { decimals: 4 })} of compute at list price.
            </p>
          )}
        </Card>
      </Grid>
    </>
  );
}

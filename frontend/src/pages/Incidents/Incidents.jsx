// Every incident the week's data raised: what happened, how fast a check
// caught it, what was done, what stops it happening twice - and what it
// would have cost without the control that caught it.

import { Link } from "react-router-dom";
import { useTheme } from "../../context/ThemeContext.jsx";
import { CHECK_LABEL, CONTROL_LABEL, fmtAud, fmtDateTime, fmtDuration, fmtInt, useApi } from "../../lib/api.js";
import { Badge, Callout, Card, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader, Stat } from "../../lib/ui.jsx";
import { SEVERITY_TONE, STATUS_TONE } from "../Desk/Desk.jsx";

const LINEAGE = {
  "INC-05": { label: "See the print in its bar", to: "/pipeline" },
  "INC-06": { label: "Decide the contract change", to: "/feeds" },
};

function Counterfactual({ r }) {
  const { t } = useTheme();
  if (!r.control) return null;
  const nothing = !r.cf_orders_changed && !r.cf_bars_changed && !r.cf_kill_switch;
  return (
    <div style={{ marginTop: 12, padding: "10px 12px", background: t.surfaceRaised, border: `1px dashed ${t.borderBright}`, borderRadius: 10 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: t.textMuted, marginBottom: 6 }}>
        Without {CONTROL_LABEL[r.control] || r.control}, re-run from raw
      </div>
      {nothing ? (
        <div style={{ fontSize: 13 }}>Nothing the desk would have seen this week - this control is insurance. It earns its place the day the failure lasts longer.</div>
      ) : (
        <KeyValues columns={3} items={[
          ["Live bars changed", fmtInt(r.cf_bars_changed)],
          ["Orders changed", fmtInt(r.cf_orders_changed)],
          ["Live P&L, week", fmtAud(r.cf_pnl_delta, { signed: true })],
          ["Worst desk mark", <span style={{ color: r.cf_worst_mark < -20000 ? t.status.critical : t.text, fontWeight: 700 }}>{fmtAud(r.cf_worst_mark)}</span>],
          ["Loss limit", r.cf_kill_switch ? <Badge tone="critical">fired {r.cf_kill_switch}</Badge> : "not reached"],
        ]} />
      )}
    </div>
  );
}

export default function Incidents() {
  const { t } = useTheme();
  const { data, error } = useApi("/api/incidents");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const real = data.incidents.filter((i) => i.incident_id.startsWith("INC"));
  const ttd = real.map((i) => i.ttd_seconds).filter((x) => x != null).sort((a, b) => a - b);

  return (
    <>
      <PageHeader
        title="Incidents"
        brief="Own production outcomes: observability, cost, latency, incidents and the work needed to prevent the same issue twice."
        subtitle="Derived from what the pipeline found, not written up afterwards. Each incident records when the defect started and when a check caught it, what it touched, the response, the change that stops it happening twice (a check and a named test), and - from the ablation - what the week would have looked like without the control."
      />
      <Grid cols={4} min={190}>
        <Stat label="Incidents" value={real.length} sub={`${real.filter((i) => i.status === "open").length} open`} emphasis />
        <Stat label="Median time to detect" value={fmtDuration(ttd[Math.floor(ttd.length / 2)])} sub="first bad event to first check failing" />
        <Stat label="Slowest to detect" value={fmtDuration(ttd[ttd.length - 1])} sub={real.find((i) => i.ttd_seconds === ttd[ttd.length - 1])?.title} />
        <Stat label="Events touched" value={fmtInt(real.reduce((a, i) => a + i.events_affected, 0))} sub="held, corrected or filled - none lost" />
      </Grid>

      {data.incidents.map((r) => (
        <Card key={r.incident_id} title={<span><Mono>{r.incident_id}</Mono> {r.title}</span>} right={
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Badge tone={SEVERITY_TONE[r.severity]}>{r.severity}</Badge>
            <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>
          </div>
        } style={{ marginBottom: 14, height: "auto" }}>
          <KeyValues columns={3} items={[
            ["Feed", `${r.venue} ${r.stream}`],
            ["Caught by", CHECK_LABEL[r.check_id] || r.check_id],
            ["Started", fmtDateTime(r.started_at)],
            ["Detected", `${fmtDateTime(r.detected_at, { ms: true })} (${fmtDuration(r.ttd_seconds)})`],
            ["Resolved", r.resolved_at ? fmtDateTime(r.resolved_at) : "not yet"],
            ["Touched", `${fmtInt(r.events_affected)} events, ${r.instruments_affected} instrument(s)`],
          ]} />
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(clamp(220px, 45%, 300px), 1fr))", gap: 12, marginTop: 12 }}>
            {[["What happened", r.what_happened], ["Root cause", r.root_cause], ["Response", r.response], ["Never twice", r.prevention]].map(([k, v]) => (
              <div key={k}>
                <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: k === "Never twice" ? t.accent : t.textMuted, marginBottom: 3 }}>{k}</div>
                <div style={{ fontSize: 13, lineHeight: 1.5 }}>{v}</div>
              </div>
            ))}
          </div>
          <Counterfactual r={r} />
          <div style={{ display: "flex", gap: 14, marginTop: 10, fontSize: 12.5, fontWeight: 650 }}>
            {LINEAGE[r.incident_id] && <Link to={LINEAGE[r.incident_id].to} style={{ color: t.accent }}>{LINEAGE[r.incident_id].label}</Link>}
            {r.alert_id && <Link to={`/triage?alert=${r.alert_id}`} style={{ color: t.accent2 }}>Triage {r.alert_id} with the agent</Link>}
          </div>
        </Card>
      ))}
      <Callout tone="neutral">
        CHK-01 is not an incident: it is the price band doing its job on a genuine move. A band that cannot release a
        confirmed move would block the desk on the days that matter most.
      </Callout>
    </>
  );
}

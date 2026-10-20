// Robustness matched to value, with the value measured: every control off in
// turn, the week re-run from raw, and the difference priced. Then the
// architecture calls, each with what would change it.

import { useTheme } from "../../context/ThemeContext.jsx";
import { CONTROL_LABEL, fmtAud, fmtInt, useApi } from "../../lib/api.js";
import { Badge, Callout, Card, ErrorNote, Loading, PageHeader, SectionTitle, Table } from "../../lib/ui.jsx";

const VERDICT_TONE = {
  "prevented a desk stop": "critical",
  "protects live bars": "serious",
  "protects research history": "warning",
  "changed orders at the margin": "neutral",
  "changed fill prices": "neutral",
  "insurance this week": "neutral",
  "cost P&L this week - by design": "ai",
};

const TIERS = [
  {
    component: "Bars, book and gate the strategy trades on",
    value: "High - every order", criticality: "Money on the next minute", lifespan: "Years",
    controls: "All tier-1 checks; contracts with versioned approval; replay with pinned hashes; a gate that blocks or degrades",
    not_built: "Second pipeline in another region; sub-second streaming (one-minute decisions do not need it)",
  },
  {
    component: "Research history (restated bars)",
    value: "High - every backtest", criticality: "Slow: wrong conclusions, not wrong orders", lifespan: "Years",
    controls: "Restatement log; point-in-time published bars kept beside final; same code path as live",
    not_built: "Bitemporal store for every field - the published/final pair answers the question asked of it",
  },
  {
    component: "Vendor backup feed",
    value: "Only when PRIMARY fails", criticality: "High in that minute", lifespan: "As long as the contract",
    controls: "Arbitration by trade id; clock measured daily and corrected inside tolerance only",
    not_built: "Real-time offset tracking - a daily estimate was tight to 0.0 ms MAD this week",
  },
  {
    component: "Triage agent",
    value: "Saves an on-call person's first ten minutes", criticality: "Low - it can only propose", lifespan: "Iterated weekly",
    controls: "Typed verdicts; frozen snapshots so runs replay; a graded eval with hard cases; visible fallback to the runbook",
    not_built: "Write access of any kind. It does not need it to be useful, and it does not pass every hard case.",
  },
  {
    component: "This demo's hosting",
    value: "A link people open a few times", criticality: "Embarrassing, not costly", lifespan: "Weeks",
    controls: "Infrastructure as code; secrets in a vault via managed identity; scale to zero; a budget alert",
    not_built: "High availability; a warm replica around the clock (a 30-60 s cold start is the accepted trade)",
  },
];

const CALLS = [
  ["Batch per session, replayable - not streaming", "Decisions are per minute and a session is the unit of recovery. A day-at-a-time pipeline replays from its files alone and proves it with digests.", "Decisions on ticks, or more than a few seconds of latency budget lost to batching."],
  ["DuckDB over parquet, rebuilt on each build", "Six hundred thousand events fit in memory; the whole week rebuilds in about a minute and a half, deterministically.", "Data that no longer fits one node, or many concurrent writers - then a lakehouse with the same contracts in front."],
  ["Contracts as YAML in the repository", "Changes go through review like code; the platform holds proposals and approvals and the YAML records the outcome.", "Many producers outside the team - then a schema registry with the same approval rule."],
  ["Hold, never guess", "A renamed field, an unknown symbol or an unconfirmed print is held until a person or a confirming fact releases it.", "Never for trading data. The cost is visible: two degraded sessions while ALT's change waits."],
  ["The model proposes, people approve", "The agent writes nothing. Its value is measured on graded cases, including the ones it fails.", "Only for actions that are reversible and graded safe across the eval, one action at a time."],
];

export default function Tradeoffs() {
  const { t } = useTheme();
  const { data, error } = useApi("/api/ablation");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const band = data.rows.find((r) => r.control === "price_band");
  const dedupe = data.rows.find((r) => r.control === "dedupe");
  const gate = data.rows.find((r) => r.control === "quality_gate");

  return (
    <>
      <PageHeader
        title="What controls are worth"
        brief="Match the level of robustness to the value, criticality, cost and expected lifespan of the solution. Make the trade-offs clear, then build what the team can operate."
        subtitle={`Every control switched off on its own, the week re-run from the raw files, and the result compared with the governed run (live model ${fmtAud(data.governed_pnl)}, worst desk mark ${fmtAud(data.governed_worst_mark)}). Some controls earned their keep this week and some changed nothing; both are findings.`}
      />

      {band && (
        <Callout tone="critical" title="The price band: the cheapest control on the platform, and the one that mattered">
          Off, one MURR print becomes the close of its bar, the desk is marked down {fmtAud(band.desk_worst_mark)}, the loss
          limit fires at {band.kill_switch.split(" ")[1]} on {band.kill_switch.split(" ")[0]} and the desk stops for the
          afternoon: {fmtInt(band.orders_changed)} orders different, {fmtAud(band.pnl_delta, { signed: true })} on the week.
          The print was wrong for eight and a half minutes.
        </Callout>
      )}

      <Card>
        <Table
          maxHeight={900}
          columns={[
            { key: "control", label: "Switched off", wrap: true, render: (r) => (
              <div style={{ minWidth: 200, maxWidth: 300 }}>
                <b>{CONTROL_LABEL[r.control] || r.control}</b>
                <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2, lineHeight: 1.4 }}>{r.description}</div>
              </div>
            ) },
            { key: "bars_changed", label: "Live bars", align: "right", render: (r) => fmtInt(r.bars_changed) },
            { key: "research_bars_changed", label: "Research bars", align: "right", render: (r) => fmtInt(r.research_bars_changed) },
            { key: "orders_changed", label: "Orders", align: "right", render: (r) => fmtInt(r.orders_changed) },
            { key: "pnl_delta", label: "P&L", align: "right", render: (r) => fmtAud(r.pnl_delta, { signed: true }) },
            { key: "desk_worst_mark", label: "Worst mark", align: "right", render: (r) => <span style={{ color: r.desk_worst_mark < -20000 ? t.status.critical : t.text, fontWeight: r.desk_worst_mark < -20000 ? 700 : 400 }}>{fmtAud(r.desk_worst_mark)}</span> },
            { key: "kill_switch", label: "Loss limit", wrap: true, render: (r) => r.kill_switch ? <Badge tone="critical">fired {r.kill_switch}</Badge> : "-" },
            { key: "verdict", label: "Verdict", wrap: true, render: (r) => <Badge tone={VERDICT_TONE[r.verdict] || "neutral"}>{r.verdict}</Badge> },
          ]}
          rows={data.rows}
        />
      </Card>
      <div style={{ height: 14 }} />
      {dedupe && (
        <Callout tone="warning" title="Dedupe protects history more than the desk">
          ALT's re-sent trades arrived after their bars were published, so only {fmtInt(dedupe.bars_changed)} live bars would
          have changed - but {fmtInt(dedupe.research_bars_changed)} restated bars would have carried doubled volume into every
          backtest of that afternoon.
        </Callout>
      )}
      {gate && (
        <Callout tone="ai" title="The gate cost money this week, on purpose">
          Without it the live model makes {fmtAud(gate.pnl_delta, { signed: true })} more: the extra comes from trading full size on
          two sessions whose consolidated volume was missing a venue. A control that never costs anything is not doing
          anything. Whether half size is the right price for incomplete data is the desk's call, made explicit here.
        </Callout>
      )}

      <SectionTitle>Robustness matched to value</SectionTitle>
      <Card>
        <Table
          columns={[
            { key: "component", label: "Component", wrap: true, render: (r) => <b>{r.component}</b> },
            { key: "value", label: "Value", wrap: true },
            { key: "criticality", label: "Criticality", wrap: true },
            { key: "lifespan", label: "Lifespan" },
            { key: "controls", label: "Built", wrap: true },
            { key: "not_built", label: "Deliberately not built", wrap: true },
          ]}
          rows={TIERS}
        />
      </Card>

      <SectionTitle>Architecture calls, and what would change them</SectionTitle>
      <Card>
        <Table
          columns={[
            { key: 0, label: "Call", wrap: true, render: (r) => <b>{r[0]}</b> },
            { key: 1, label: "Why", wrap: true, render: (r) => r[1] },
            { key: 2, label: "What would change it", wrap: true, render: (r) => r[2] },
          ]}
          rows={CALLS}
        />
      </Card>
    </>
  );
}

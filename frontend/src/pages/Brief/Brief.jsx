// The advertisement's own list, mapped to where each point is shown working,
// then the first ninety days - as a plan to learn the real system first.

import { Link } from "react-router-dom";
import { useTheme } from "../../context/ThemeContext.jsx";
import { Callout, Card, Grid, PageHeader, SectionTitle, Table } from "../../lib/ui.jsx";

const OWN = [
  ["Build dependable ingestion, storage and query layers for raw, changing event and trading data.",
   "Three feeds in three shapes, landed and hashed; one canonical trade; a governed DuckDB store; a public, validated query layer.",
   [["Desk view", "/desk"], ["Query layer", "/query"]]],
  ["Work with the teams that use them to define data contracts, and make validation, lineage and recovery part of the design.",
   "Six contracts naming their consumers and SLAs; ten checks with stated actions; lineage from any bar to file and row; replay that proves itself.",
   [["Feeds & contracts", "/feeds"], ["Pipeline & lineage", "/pipeline"], ["Replay & recovery", "/recovery"]]],
  ["Build and improve pipelines from ingestion through validation, deployment and monitoring.",
   "Twelve timed stages, per-day independence, a run ledger with cost, a deterministic build verified against pinned digests.",
   [["Pipeline & lineage", "/pipeline"], ["Operations", "/operations"]]],
  ["Choose practical architecture... match the level of robustness to the value, criticality, cost and expected lifespan. Make the trade-offs clear.",
   "Every control switched off in turn and priced; a tiering table that says what was deliberately not built and why.",
   [["What controls are worth", "/tradeoffs"]]],
  ["Use cloud infrastructure, infrastructure as code, testing and CI/CD to make environments reproducible and releases safe.",
   "Terraform for the whole deployment; secrets by managed identity; tests across pipeline, workflow and pages; the data itself reproducible.",
   [["Operations", "/operations"]]],
  ["Build and operate practical AI and agentic workflows where they solve a real problem. Measure outputs and make failure modes visible.",
   "A tool-calling triage agent graded against the runbook on 33 labelled cases, failures listed one by one, advisory only.",
   [["AI triage", "/triage"]]],
  ["Own production outcomes: observability, cost, latency, incidents and the work needed to prevent the same issue twice.",
   "Incidents derived from the data with time to detect, response and a named check and test that stop a repeat; latency and cost measured.",
   [["Incidents", "/incidents"], ["Operations", "/operations"]]],
  ["Put decision workflows and model outputs to work in production.",
   "A live model trading through a quality gate under a loss limit, a shadow model beside it, promotion decided by a rule agreed in advance.",
   [["Decisions & models", "/decisions"]]],
];

const PLAN = [
  {
    when: "Days 1-30: learn what is there",
    items: [
      "Sit with the trading and research teams. List every feed, where it lands, who reads it, and what each reader assumes about it.",
      "Trace the last few real incidents end to end: how they were noticed, how long that took, and what would have caught them sooner.",
      "Write the first two contracts with the people who consume those feeds - the two the desk depends on most - and agree what happens when one breaks.",
      "Get one feed replaying from raw with a digest, so 'did the data change or did the code?' has an answer.",
    ],
  },
  {
    when: "Days 31-60: make the data layer dependable",
    items: [
      "Contracts and checks for the remaining market feeds, with quarantine instead of silent drops and a record of every hold.",
      "Point-in-time history beside the final one, so research and production read the same data the same way.",
      "Contracts and pipeline tests in CI; releases that can be rolled back; time to detect measured, not guessed.",
    ],
  },
  {
    when: "Days 61-90: put it to work where it pays",
    items: [
      "Wire data quality into the decision path where the team agrees it should be - a gate, a size cap, a stop - priced the way the ablation prices it here.",
      "Observability the team will actually look at: freshness, latency, cost and incidents on one page.",
      "Pilot agentic triage on the team's own past incidents, advisory only, measured against the runbook before anyone relies on it.",
      "Review the tiering with the team: what is over-built, what is under-built, what to stop.",
    ],
  },
];

export default function Brief() {
  const { t } = useTheme();
  return (
    <>
      <PageHeader
        title="First 90 days"
        subtitle="The advertisement's own list, mapped to where each point is shown working on this platform. Then a plan for the first ninety days - which starts by learning the real system, because the right controls are the ones that fit the data and the decisions you actually have."
      />
      <Callout tone="neutral" title="What this is and is not">
        Built for this application, on synthetic data, and named for the firm it was built for. It is not affiliated
        with or endorsed by Edge Stackers. The feeds, venues, instruments and strategy are invented; the defects are
        the kind real feeds have. Nothing here is based on how Edge Stackers works, which is the first thing to learn.
      </Callout>
      <SectionTitle>What you will own, and where it is shown</SectionTitle>
      <Card>
        <Table
          columns={[
            { key: 0, label: "From the advertisement", wrap: true, render: (r) => <i style={{ color: t.textMuted }}>"{r[0]}"</i> },
            { key: 1, label: "Here", wrap: true, render: (r) => r[1] },
            { key: 2, label: "Open", render: (r) => (
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {r[2].map(([label, to]) => <Link key={to} to={to} style={{ color: t.accent, fontWeight: 650, fontSize: 12.5 }}>{label}</Link>)}
              </div>
            ) },
          ]}
          rows={OWN}
        />
      </Card>

      <SectionTitle>The first ninety days</SectionTitle>
      <Grid cols={3} min={300}>
        {PLAN.map((p) => (
          <Card key={p.when} title={p.when}>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.6 }}>
              {p.items.map((i) => <li key={i} style={{ marginBottom: 6 }}>{i}</li>)}
            </ul>
          </Card>
        ))}
      </Grid>

      <SectionTitle>Questions I would ask first</SectionTitle>
      <Card>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.7 }}>
          <li>Which feeds and venues matter most to the desk today, and which one failed last?</li>
          <li>How does research get point-in-time data now, and has a backtest ever been wrong because of a restatement?</li>
          <li>How does a model output reach production, and who can stop it?</li>
          <li>Where is the line between what the data team owns and what the trading team owns?</li>
          <li>Which incidents keep coming back?</li>
        </ul>
      </Card>
    </>
  );
}

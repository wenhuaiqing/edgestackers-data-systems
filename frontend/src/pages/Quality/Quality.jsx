// The check catalogue - what each one looks for, what it does on failure,
// and what it caught this week - and every held event, browsable.

import { useState } from "react";
import { useTheme } from "../../context/ThemeContext.jsx";
import { CHECK_LABEL, fmtDate, fmtInt, fmtTime, useApi } from "../../lib/api.js";
import {
  Badge, Card, ErrorNote, Loading, Mono, PageHeader, SectionTitle, Select, Table,
} from "../../lib/ui.jsx";

const DAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"];

export default function Quality() {
  const { t } = useTheme();
  const { data, error } = useApi("/api/quality");
  const [check, setCheck] = useState("price_band");
  const [venue, setVenue] = useState("");
  const [day, setDay] = useState("");
  const qs = new URLSearchParams({ ...(check && { check }), ...(venue && { venue }), ...(day && { day }), limit: "200" });
  const { data: rows } = useApi(`/api/quarantine?${qs}`);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  const grid = {};
  for (const r of data.counts) {
    grid[r.check_id] ??= {};
    grid[r.check_id][r.day] = (grid[r.check_id][r.day] || 0) + r.n;
  }

  return (
    <>
      <PageHeader
        title="Checks & quarantine"
        brief="Make validation, lineage and recovery part of the design."
        subtitle="Ten checks, each with a stated reason and a stated action on failure. Nothing fails silently and nothing is dropped without a record: every event a check touches is held, quarantined or corrected in the open, with the time it was caught and how it was resolved."
      />
      <Card title="Check catalogue" hint="Tier 1 checks protect what the desk trades on and block or degrade the gate; tier 2 protect history and log restatements.">
        <Table
          columns={[
            { key: "check_id", label: "Check", render: (r) => <b>{CHECK_LABEL[r.check_id] || r.check_id}</b> },
            { key: "applies_to", label: "Applies to" },
            { key: "what", label: "What it looks for", wrap: true },
            { key: "on_fail", label: "On failure", wrap: true },
            { key: "tier", label: "Tier", render: (r) => <Badge tone={r.tier === 1 ? "critical" : "neutral"}>tier {r.tier}</Badge> },
            { key: "fired", label: "This week", align: "right", render: (r) => fmtInt(r.fired) },
            { key: "incidents", label: "Incidents", render: (r) => r.incidents.join(", ") || "-" },
          ]}
          rows={data.catalogue}
          maxHeight={600}
        />
      </Card>

      <SectionTitle>Held and quarantined, by session</SectionTitle>
      <Card>
        <Table
          columns={[
            { key: "check", label: "Check", render: (r) => CHECK_LABEL[r.check] || r.check },
            ...DAYS.map((d) => ({ key: d, label: fmtDate(d), align: "right", render: (r) => r[d] ? fmtInt(r[d]) : "-" })),
          ]}
          rows={Object.entries(grid).map(([check, byDay]) => ({ check, ...byDay }))}
        />
      </Card>

      <SectionTitle right={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Select label="Check" value={check} onChange={setCheck}
                  options={[{ value: "", label: "Any" }, ...Object.keys(grid).map((c) => ({ value: c, label: CHECK_LABEL[c] || c }))]} />
          <Select label="Feed" value={venue} onChange={setVenue} options={[{ value: "", label: "Any" }, "PRIMARY", "ALT", "VENDOR"]} />
          <Select label="Session" value={day} onChange={setDay} options={[{ value: "", label: "Any" }, ...DAYS.map((d) => ({ value: d, label: fmtDate(d) }))]} />
        </div>
      }>Quarantine browser</SectionTitle>
      <Card hint="The first 200 matching events. Each keeps its raw file and row, so it can be re-examined or released without guessing where it came from.">
        <Table
          maxHeight={480}
          columns={[
            { key: "check_id", label: "Check", render: (r) => CHECK_LABEL[r.check_id] || r.check_id },
            { key: "venue", label: "Feed" },
            { key: "symbol", label: "Symbol" },
            { key: "ts_exchange", label: "Exchange time", render: (r) => `${fmtDate(r.ts_exchange)} ${fmtTime(r.ts_exchange, { ms: true })}` },
            { key: "detected_at", label: "Caught", render: (r) => fmtTime(r.detected_at, { ms: true }) },
            { key: "reason", label: "Reason", wrap: true },
            { key: "resolution", label: "Resolution", wrap: true },
            { key: "file", label: "Raw file, row", render: (r) => <Mono dim>{r.file}#{r.raw_row}</Mono> },
          ]}
          rows={rows || []}
          empty="Nothing held for that filter."
        />
        <p style={{ fontSize: 12, color: t.textMuted, margin: "8px 0 0" }}>Times are exchange-local (AEDT).</p>
      </Card>
    </>
  );
}

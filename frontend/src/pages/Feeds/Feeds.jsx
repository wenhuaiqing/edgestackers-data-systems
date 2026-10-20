// Contracts with the teams that consume the data, the partitions judged
// against them, and the one change waiting on a decision.

import { useState } from "react";
import { Check, X } from "lucide-react";
import { useTheme } from "../../context/ThemeContext.jsx";
import { actorName, setActorName, writeToken } from "../../config.js";
import {
  SOURCE_LABEL, apiWrite, fmtAud, fmtDate, fmtDateTime, fmtInt, fmtMs, fmtNum, pct, useApi,
} from "../../lib/api.js";
import {
  Badge, Button, CTAButton, Callout, Card, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader,
  SectionTitle, Table,
} from "../../lib/ui.jsx";

function Proposal({ p, onDone }) {
  const { t } = useTheme();
  const [name, setName] = useState(actorName());
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState(null);
  const [err, setErr] = useState(null);
  const ev = p.evidence;
  const pv = p.preview;

  const decide = async (approve) => {
    setActorName(name);
    setBusy(true);
    setErr(null);
    try {
      const res = await apiWrite(`/api/proposals/${p.proposal_id}/${approve ? "approve" : "reject"}`, { note: "" });
      setOutcome(res);
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={`${p.proposal_id}: ${p.subject}`} right={<Badge tone={p.status === "pending" ? "warning" : p.status === "approved" ? "good" : "neutral"}>{p.status}</Badge>}>
      <p style={{ fontSize: 13, margin: "0 0 12px", lineHeight: 1.55 }}>{p.summary}</p>
      <KeyValues items={[
        ["Proposed by", <><Badge tone="ai">{p.proposed_by}</Badge> at {fmtDateTime(p.proposed_at)}</>],
        ["Effective from", fmtDate(p.effective_from)],
        ["Decided", p.decided_by ? `${p.decided_by}, ${fmtDateTime(p.decided_at)}` : "not yet"],
      ]} />

      <SectionTitle>Evidence, computed from the raw files before anyone is asked</SectionTitle>
      <Callout tone={ev.same_distribution ? "good" : "critical"}>{ev.verdict}</Callout>
      <KeyValues columns={3} items={[
        ["Renamed", <Mono>{ev.renamed_field}</Mono>],
        ["Added", <Mono>{ev.added_field}</Mono>],
        ["KS statistic", `${fmtNum(ev.ks_statistic, 4)} (1% critical ${fmtNum(ev.ks_critical_1pct, 4)})`],
        ["Median before / after", `${fmtInt(ev.median_before)} / ${fmtInt(ev.median_after)}`],
        ["Mean ratio", fmtNum(ev.mean_ratio, 3)],
        ["liquidity_flag", Object.entries(ev.liquidity_flag_values).map(([k, v]) => `${k} ${pct(v, 1)}`).join(", ")],
      ]} />

      <SectionTitle>What approving it changes (previewed by a full re-run)</SectionTitle>
      <Table
        columns={[
          { key: "k", label: "Measure" },
          { key: "before", label: "Now", align: "right" },
          { key: "after", label: "If approved", align: "right" },
        ]}
        rows={[
          { k: "ALT trades held by the contract", before: fmtInt(pv.trades_released), after: "0" },
          { k: "ALT share of volume, 15/10 to 16/10", before: pct(pv.alt_volume_share_before), after: pct(pv.alt_volume_share_after) },
          { k: "Instrument-minutes degraded by the gate", before: fmtInt(pv.degraded_minutes_before), after: fmtInt(pv.degraded_minutes_after) },
          { k: "Live model P&L, week", before: fmtAud(pv.live_pnl_before), after: fmtAud(pv.live_pnl_after) },
        ]}
      />
      <p style={{ fontSize: 12, color: t.textMuted, margin: "8px 0 0" }}>
        Released trades still go through every other check: the preview finds{" "}
        {Object.entries(pv.new_quarantine).map(([k, v]) => `${fmtInt(v)} ${k.replace(/_/g, " ")}`).join(", ")} across the week once ALT is back in.
      </p>

      {p.status === "pending" && (
        <div style={{ marginTop: 16, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, color: t.textMuted }}>
            Deciding as{" "}
            <input value={name} onChange={(e) => setName(e.target.value)} style={{
              background: t.surface, color: t.text, border: `1px solid ${t.border}`, borderRadius: 8, padding: "6px 9px",
              fontSize: 12.5, fontFamily: "inherit", width: 150,
            }} />
          </label>
          <CTAButton icon={Check} onClick={() => decide(true)} disabled={busy}>{busy ? "Reprocessing the week..." : "Approve and reprocess"}</CTAButton>
          <Button icon={X} onClick={() => decide(false)} disabled={busy}>Reject</Button>
          {!writeToken() && <span style={{ fontSize: 12, color: t.textMuted }}>This link is read-only; the server will say why it refuses. Try deciding as "triage-agent" to see separation of duties.</span>}
        </div>
      )}
      {err && <div style={{ marginTop: 12 }}><Callout tone="critical" title={`Refused (${err.status})`}>{err.message}</Callout></div>}
      {outcome?.status === "approved" && (
        <div style={{ marginTop: 12 }}>
          <Callout tone="good" title={`Approved. ${outcome.run.run_id} reprocessed the week from raw in ${fmtMs(outcome.run.wall_ms)}.`}>
            Live P&L {fmtAud(outcome.before.live_pnl)} to {fmtAud(outcome.after.live_pnl)}; degraded minutes{" "}
            {fmtInt(outcome.before.degraded_minutes)} to {fmtInt(outcome.after.degraded_minutes)}; ALT share on 15/10 to 16/10{" "}
            {pct(outcome.before.alt_volume_share_15_16)} to {pct(outcome.after.alt_volume_share_15_16)}. Every page now reads the new run.
          </Callout>
        </div>
      )}
    </Card>
  );
}

function ContractCard({ c, platform }) {
  const { t } = useTheme();
  const [open, setOpen] = useState(false);
  const v1 = c.versions[0];
  const extra = platform.filter((v) => v.contract_id === c.contract_id);
  return (
    <Card title={<Mono>{c.contract_id}</Mono>} right={<span style={{ fontSize: 11.5, color: t.textMuted }}>{c.file}</span>}>
      <KeyValues items={[
        ["Owner", c.owner],
        ["Key", <Mono>{c.key}</Mono>],
        ["SLA", Object.entries(c.sla).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join("; ")],
        ["Checks", c.checks],
      ]} />
      <div style={{ marginTop: 12 }}>
        {c.consumers.map((x) => (
          <div key={x.team} style={{ fontSize: 12.5, marginBottom: 5, lineHeight: 1.45 }}>
            <b>{x.team}</b>: {x.needs}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0" }}>
        {c.versions.map((v) => <Badge key={v.version} tone="good">v{v.version} {v.status}, from {fmtDate(v.effective_from)}</Badge>)}
        {extra.map((v) => <Badge key={`p${v.version}`} tone="good">v{v.version} approved on the platform by {v.approved_by}</Badge>)}
      </div>
      {c.mapping && <p style={{ fontSize: 12, color: t.textMuted, margin: "0 0 8px" }}>Mapped onto the canonical trade: {Object.entries(c.mapping).map(([k, v]) => `${k} to ${typeof v === "string" ? v : v.field}`).join(", ")}.</p>}
      {c.clock_offset && <p style={{ fontSize: 12, color: t.textMuted, margin: "0 0 8px" }}>Clock: {c.clock_offset.method}; applied only with at least {c.clock_offset.apply_when.min_matched} matches and a MAD under {c.clock_offset.apply_when.max_mad_ms} ms.</p>}
      <Button onClick={() => setOpen((x) => !x)}>{open ? "Hide fields" : `Fields (${Object.keys(v1.fields).length})`}</Button>
      {open && (
        <div style={{ marginTop: 10 }}>
          <Table
            columns={[
              { key: "name", label: "Field", render: (r) => <Mono>{r.name}</Mono> },
              { key: "type", label: "Type" },
              { key: "rule", label: "Rule", wrap: true },
            ]}
            rows={Object.entries(v1.fields).map(([name, f]) => ({
              name, type: f.type,
              rule: [f.required ? "required" : "optional", f.nullable_when && `null when ${f.nullable_when}`,
                f.enum && `one of ${f.enum.join(", ")}`, f.min_exclusive != null && `> ${f.min_exclusive}`].filter(Boolean).join("; "),
            }))}
          />
        </div>
      )}
    </Card>
  );
}

export default function Feeds() {
  const { data, error, reload } = useApi("/api/feeds");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader
        title="Feeds & contracts"
        brief="Work with the teams that use them to define data contracts, and make validation, lineage and recovery part of the design."
        subtitle="Each feed has a contract agreed with the teams that consume it: its fields, its key, its freshness SLA and the checks it must pass. A partition that breaks its contract is quarantined whole. A change to a contract is a new version, proposed with evidence and approved by someone other than the proposer."
      />

      {data.proposals.map((p) => <Proposal key={p.proposal_id} p={p} onDone={reload} />)}

      <SectionTitle>Contracts</SectionTitle>
      <Grid cols={3} min={360}>
        {data.contracts.map((c) => <ContractCard key={c.contract_id} c={c} platform={data.platform_versions} />)}
      </Grid>

      <Grid cols={2} min={460}>
        <Card title="Latency against the contract" hint="Receive time minus the feed's own exchange time. Negative means the feed claims an event arrived before it happened.">
          <Table
            maxHeight={360}
            columns={[
              { key: "source", label: "Feed", render: (r) => SOURCE_LABEL[r.source] || r.source },
              { key: "day", label: "Session", render: (r) => fmtDate(r.day) },
              { key: "p50_ms", label: "p50", align: "right", render: (r) => fmtMs(r.p50_ms) },
              { key: "p99_ms", label: "p99", align: "right", render: (r) => fmtMs(r.p99_ms) },
              { key: "negative_share", label: "Negative", align: "right", render: (r) => r.negative_share > 0.01
                ? <Badge tone="critical">{pct(r.negative_share)}</Badge> : pct(r.negative_share) },
              { key: "late_share", label: "After watermark", align: "right", render: (r) => pct(r.late_share, 2) },
            ]}
            rows={data.latency}
          />
        </Card>
        <Card title="Vendor clock, measured against PRIMARY" hint="Same trade, two timestamps. Corrected only inside the contract's tolerance.">
          <Table
            columns={[
              { key: "day", label: "Session", render: (r) => fmtDate(r.day) },
              { key: "median_ms", label: "Offset", align: "right", render: (r) => `${fmtNum(r.median_ms, 1)} ms` },
              { key: "mad_ms", label: "MAD", align: "right", render: (r) => `${fmtNum(r.mad_ms, 2)} ms` },
              { key: "matched", label: "Matched", align: "right", render: (r) => fmtInt(r.matched) },
              { key: "applied_ms", label: "Applied", render: (r) => r.applied_ms ? <Badge tone="warning">{`${fmtNum(-r.applied_ms, 0)} ms`}</Badge> : <Badge tone="good">none needed</Badge> },
              { key: "negative_latency_after", label: "Negative after", align: "right", render: (r) => `${fmtInt(r.negative_latency_before)} to ${fmtInt(r.negative_latency_after)}` },
            ]}
            rows={data.clock_offsets}
          />
        </Card>
      </Grid>

      <Card title="Raw files" hint="Every file hashed on landing; the hashes are pinned in the repository and checked by every replay.">
        <Table
          maxHeight={420}
          columns={[
            { key: "day", label: "Session", render: (r) => fmtDate(r.day) },
            { key: "file", label: "File", render: (r) => <Mono>{r.file}</Mono> },
            { key: "rows", label: "Rows", align: "right", render: (r) => fmtInt(r.rows) },
            { key: "version", label: "Contract", render: (r) => `${r.contract} v${r.version}` },
            { key: "ok", label: "Judged", render: (r) => r.ok ? <Badge tone="good">conforms</Badge> : <Badge tone="critical">{r.reason}</Badge> },
            { key: "arrived_at", label: "Arrived", render: (r) => fmtDateTime(r.arrived_at) },
            { key: "sha256", label: "SHA-256", render: (r) => <Mono dim>{r.sha256?.slice(0, 12)}</Mono> },
          ]}
          rows={data.files}
        />
      </Card>
    </>
  );
}

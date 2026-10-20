// The run that produced every table, stage by stage, and lineage from any
// bar back to the raw file and row each of its events came from.

import { useMemo, useState } from "react";
import { ComposedChart, Line, ReferenceArea, ReferenceLine, Scatter } from "recharts";
import { useTheme } from "../../context/ThemeContext.jsx";
import {
  CHECK_LABEL, SOURCE_LABEL, fmtAud, fmtDate, fmtInt, fmtMs, fmtNum, fmtTime, useApi,
} from "../../lib/api.js";
import {
  Badge, Callout, Card, ChartFrame, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader, SectionTitle,
  Select, Table, useChartParts,
} from "../../lib/ui.jsx";

const DAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"];
const STATUS_TONE = { accepted: "good", redundant: "neutral", duplicate: "warning", held: "critical", cancelled: "serious" };

function Stages({ stages }) {
  const { t } = useTheme();
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(clamp(132px, 46%, 150px), 1fr))", gap: 8, marginBottom: 14 }}>
      {stages.map((s, i) => (
        <div key={s.stage} style={{ background: t.surface, border: `1px solid ${t.border}`, borderRadius: 10, padding: "10px 11px", minWidth: 0 }}>
          <div style={{ fontSize: 10.5, color: t.textMuted, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase" }}>
            {i + 1}. {s.stage}
          </div>
          <div style={{ fontSize: 17, fontWeight: 700, margin: "4px 0 2px" }}>{fmtInt(s.rows_out)}</div>
          <div style={{ fontSize: 11, color: t.textMuted }}>from {fmtInt(s.rows_in)} in {fmtMs(s.wall_ms)}</div>
          {s.quarantined > 0 && <div style={{ marginTop: 5 }}><Badge tone="warning">{fmtInt(s.quarantined)} held</Badge></div>}
          {s.note && <div style={{ fontSize: 11, color: t.textMuted, marginTop: 5, lineHeight: 1.35 }}>{s.note}</div>}
        </div>
      ))}
    </div>
  );
}

function Lineage({ instrument, minute }) {
  const { t } = useTheme();
  const { data, error } = useApi(minute ? `/api/lineage?instrument=${instrument}&minute=${encodeURIComponent(minute)}` : null);
  if (!minute) return <Card title="Lineage"><p style={{ fontSize: 13, color: t.textMuted }}>Click a minute on the chart.</p></Card>;
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const b = data.bar;
  return (
    <Card title={`Lineage: ${instrument} at ${fmtTime(minute, { seconds: false })} on ${fmtDate(minute)}`}
          hint="Every event that could belong to this bar, from every feed, with what each check did to it.">
      {b ? (
        <Table
          columns={[
            { key: "k", label: "" },
            { key: "pub", label: "As first published", align: "right" },
            { key: "fin", label: "As finally known", align: "right" },
          ]}
          rows={[
            { k: "Trades", pub: fmtInt(b.pub_trades), fin: fmtInt(b.trades) },
            { k: "Volume", pub: fmtInt(b.pub_volume), fin: fmtInt(b.volume) },
            { k: "Close", pub: fmtNum(b.pub_close, 3), fin: fmtNum(b.close, 3) },
            { k: "VWAP", pub: fmtNum(b.pub_vwap, 4), fin: fmtNum(b.vwap, 4) },
            { k: "High", pub: fmtNum(b.pub_high, 3), fin: fmtNum(b.high, 3) },
          ]}
        />
      ) : <Callout tone="warning">No bar: nothing usable traded in this minute.</Callout>}
      <div style={{ height: 10 }} />
      <KeyValues columns={3} items={[
        ["Gate", data.gate ? <Badge tone={data.gate.state === "open" ? "good" : data.gate.state === "blocked" ? "critical" : "warning"}>{data.gate.state}{data.gate.reason ? `: ${data.gate.reason}` : ""}</Badge> : "-"],
        ["Book", data.book ? `${fmtNum(data.book.best_bid, 3)} / ${fmtNum(data.book.best_ask, 3)} from ${data.book.venues_quoting} venue(s)` : "-"],
        ["Restated", data.restatement ? data.restatement.cause : "no"],
        ["Produced by", data.run ? <Mono>{data.run.run_id}</Mono> : "-"],
        ["Code", <Mono>{data.run?.git_sha || "dev build"}</Mono>],
        ["Contracts", data.run?.contract_versions],
      ]} />
      <SectionTitle>Events</SectionTitle>
      <Table
        maxHeight={380}
        columns={[
          { key: "source", label: "Feed", render: (r) => r.source },
          { key: "trade_id", label: "Trade id", render: (r) => <Mono>{r.trade_id || r.event_id}</Mono> },
          { key: "event_type", label: "Type", render: (r) => r.event_type === "trade" ? "trade" : <Badge tone="serious">cancel</Badge> },
          { key: "ts_exchange", label: "Exchange time", render: (r) => <span title={r.offset_ms ? `raw ${fmtTime(r.ts_exchange_raw, { ms: true })}` : ""}>{fmtTime(r.ts_exchange, { ms: true })}{r.offset_ms ? ` (${fmtNum(-r.offset_ms, 0)} ms)` : ""}</span> },
          { key: "ts_received", label: "Received", render: (r) => fmtTime(r.ts_received, { ms: true }) },
          { key: "ts_available", label: "Usable from", render: (r) => r.ts_available ? fmtTime(r.ts_available, { ms: true }) : "never" },
          { key: "price", label: "Price", align: "right", render: (r) => fmtNum(r.price, 3) },
          { key: "qty", label: "Qty", align: "right", render: (r) => fmtInt(r.qty) },
          { key: "status", label: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{r.status}</Badge> },
          { key: "in", label: "In bar", render: (r) => `${r.in_published ? "published" : "-"} / ${r.in_final ? "final" : "-"}` },
          { key: "flags", label: "Flags", render: (r) => (r.flags || "").split(";").filter(Boolean).join(", ") },
          { key: "file", label: "Raw file, row", render: (r) => <Mono dim>{r.file}#{r.raw_row}</Mono> },
        ]}
        rows={data.events}
        empty="No events in this minute."
      />
      {data.quarantine.length > 0 && (
        <>
          <SectionTitle>Held or quarantined</SectionTitle>
          <Table
            columns={[
              { key: "check_id", label: "Check", render: (r) => CHECK_LABEL[r.check_id] || r.check_id },
              { key: "reason", label: "Reason", wrap: true },
              { key: "resolution", label: "Resolution", wrap: true },
              { key: "resolved_at", label: "When", render: (r) => r.resolved_at ? fmtTime(r.resolved_at) : "-" },
            ]}
            rows={data.quarantine}
          />
        </>
      )}
      {data.orders.length > 0 && (
        <>
          <SectionTitle>Orders touching this minute</SectionTitle>
          <Table
            columns={[
              { key: "model_id", label: "Model" },
              { key: "decided_at", label: "Decided", render: (r) => fmtTime(r.decided_at, { seconds: false }) },
              { key: "executed_at", label: "Executed", render: (r) => fmtTime(r.executed_at, { seconds: false }) },
              { key: "side", label: "Side" },
              { key: "qty", label: "Qty", align: "right", render: (r) => fmtInt(r.qty) },
              { key: "price", label: "Price", align: "right", render: (r) => fmtNum(r.price, 3) },
              { key: "reason", label: "Reason" },
            ]}
            rows={data.orders}
          />
        </>
      )}
      <SectionTitle>Files</SectionTitle>
      <Table
        columns={[
          { key: "file", label: "File", render: (r) => <Mono>{r.file}</Mono> },
          { key: "contract", label: "Contract", render: (r) => `${r.contract} v${r.version}` },
          { key: "ok", label: "Judged", render: (r) => <Badge tone={r.ok ? "good" : "critical"}>{r.ok ? "conforms" : "quarantined"}</Badge> },
          { key: "sha256", label: "SHA-256", render: (r) => <Mono dim>{r.sha256}</Mono> },
        ]}
        rows={data.files}
      />
    </Card>
  );
}

export default function Pipeline() {
  const { t } = useTheme();
  const chart = useChartParts();
  const { data, error } = useApi("/api/pipeline");
  const [instrument, setInstrument] = useState("INS-013");
  const [day, setDay] = useState("2026-10-14");
  const [minute, setMinute] = useState("2026-10-14T12:28:00");
  const { data: bars } = useApi(`/api/bars?instrument=${instrument}&day=${day}`);

  const series = useMemo(() => (bars?.series || []).map((r) => ({
    ...r, label: fmtTime(r.minute, { seconds: false }),
    restatedMark: r.restated ? r.close : null,
  })), [bars]);
  const spans = useMemo(() => {
    const out = [];
    let cur = null;
    for (const r of series) {
      const state = r.gate || "open";
      if (state !== "open") {
        if (cur && cur.state === state) cur.end = r.label;
        else { if (cur) out.push(cur); cur = { state, start: r.label, end: r.label }; }
      } else if (cur) { out.push(cur); cur = null; }
    }
    if (cur) out.push(cur);
    return out;
  }, [series]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const inst = data.instruments.find((i) => i.instrument_id === instrument);

  return (
    <>
      <PageHeader
        title="Pipeline & lineage"
        brief="Build and improve pipelines from ingestion through validation, deployment and monitoring."
        subtitle="Twelve stages from raw files to the gate the strategy trades through. Each day runs independently, so any session can be replayed from its files alone. Any bar traces back to the file and row of every event in it, what each check did to the event, and the run, code and contract versions that produced it."
      />
      <SectionTitle right={<span style={{ fontSize: 12, color: t.textMuted }}>{data.run_id}</span>}>Stages of the run behind every table</SectionTitle>
      <Stages stages={data.stages} />

      <Card title="Bars, as published and as finally known" right={
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Select label="Instrument" value={instrument} onChange={(v) => { setInstrument(v); setMinute(null); }}
                  options={data.instruments.map((i) => ({ value: i.instrument_id, label: `${i.symbol} (${i.instrument_id})` }))} />
          <Select label="Session" value={day} onChange={(v) => { setDay(v); setMinute(null); }} options={DAYS.map((d) => ({ value: d, label: fmtDate(d) }))} />
        </div>
      } hint={`${inst?.symbol}: close each minute as the strategy saw it and as known after every correction. Shaded: minutes the gate degraded (amber) or blocked (red). Click any minute for its lineage.`}>
        <ChartFrame height={300}>
          <ComposedChart data={series} margin={{ left: 4, right: 12, top: 8 }}
                         onClick={(e) => { const p = e?.activePayload?.[0]?.payload; if (p) setMinute(p.minute); }}>
            {chart.grid}
            {chart.xAxis({ dataKey: "label", interval: 29, minTickGap: 20 })}
            {chart.yAxis({ domain: ["auto", "auto"], tickFormatter: (v) => fmtNum(v, 2) })}
            {chart.tooltip({ formatter: (v, n) => [fmtNum(v, 3), n] })}
            {chart.legend()}
            {spans.map((s) => (
              <ReferenceArea key={`${s.state}${s.start}`} x1={s.start} x2={s.end} ifOverflow="extendDomain"
                             fill={s.state === "blocked" ? t.status.critical : t.status.warning} fillOpacity={s.state === "blocked" ? 0.18 : 0.07} />
            ))}
            {minute && <ReferenceLine x={fmtTime(minute, { seconds: false })} stroke={t.accent} strokeDasharray="4 3" />}
            <Line type="stepAfter" dataKey="pub_close" name="Close, as published" stroke={t.series[0]} dot={false} strokeWidth={1.6} isAnimationActive={false} />
            <Line type="stepAfter" dataKey="close" name="Close, final" stroke={t.series[1]} dot={false} strokeWidth={1.2} strokeDasharray="4 2" isAnimationActive={false} />
            <Scatter dataKey="restatedMark" name="Restated" fill={t.status.critical} isAnimationActive={false} />
          </ComposedChart>
        </ChartFrame>
        {bars?.held?.length > 0 && (
          <p style={{ fontSize: 12, color: t.textMuted, margin: "6px 0 0" }}>
            Held this session: {bars.held.slice(0, 4).map((h) => `${CHECK_LABEL[h.check_id] || h.check_id} at ${fmtTime(h.ts_exchange)}`).join("; ")}
            {bars.held.length > 4 ? `, and ${bars.held.length - 4} more` : ""}.
          </p>
        )}
      </Card>
      <div style={{ height: 14 }} />
      <Lineage instrument={instrument} minute={minute} />

      <Grid cols={2} min={420}>
        <Card title="What happened to every trade event" hint="Redundant: the vendor's copy of a PRIMARY trade the direct feed delivered - kept for lineage and arbitration, never double-counted.">
          <Table
            columns={[
              { key: "source", label: "Feed", render: (r) => SOURCE_LABEL[r.source] || r.source },
              { key: "status", label: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{r.status}</Badge> },
              { key: "n", label: "Events", align: "right", render: (r) => fmtInt(r.n) },
            ]}
            rows={data.status_counts}
          />
        </Card>
        <Card title="Partition digests" hint="What a replay must reproduce. Recorded by the run that produced the current tables.">
          <Table
            maxHeight={330}
            columns={[
              { key: "partition", label: "Partition", render: (r) => <Mono>{r.partition}</Mono> },
              { key: "rows", label: "Rows", align: "right", render: (r) => fmtInt(r.rows) },
              { key: "sha256", label: "SHA-256", render: (r) => <Mono dim>{r.sha256.slice(0, 16)}</Mono> },
            ]}
            rows={data.partitions}
          />
        </Card>
      </Grid>
      <p style={{ fontSize: 12, color: t.textMuted }}>
        Runs to date: {data.runs.map((r) => `${r.run_id} (${r.kind}, ${fmtMs(r.wall_ms)}, ${fmtAud(r.cost_aud, { decimals: 4 })})`).join("; ")}.
      </p>
    </>
  );
}

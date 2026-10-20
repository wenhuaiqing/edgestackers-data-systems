// Replay a session from its raw files and prove the output is identical;
// the restatement log; and why decisions never read a restated bar.

import { useState } from "react";
import { Play } from "lucide-react";
import { useTheme } from "../../context/ThemeContext.jsx";
import { api, fmtAud, fmtDate, fmtDateTime, fmtInt, fmtMs, fmtNum, fmtTime, useApi } from "../../lib/api.js";
import {
  Badge, CTAButton, Callout, Card, ErrorNote, Grid, Loading, Mono, PageHeader, SectionTitle, Select, Table,
} from "../../lib/ui.jsx";

const DAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"];

export default function Recovery() {
  const { t } = useTheme();
  const { data, error } = useApi("/api/pipeline");
  const [day, setDay] = useState("2026-10-14");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  const run = async () => {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await api("/api/replay", { method: "POST", body: { day } }));
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;

  return (
    <>
      <PageHeader
        title="Replay & recovery"
        brief="Make validation, lineage and recovery part of the design."
        subtitle="Recovery is only as good as the proof that a re-run gives the same answer. Each session can be replayed from its raw files alone: the files are re-hashed against the digests pinned in the repository, the session is re-run under the contract versions in force, and every governed partition is compared with the digest the current tables were built from."
      />
      <Card title="Replay a session from raw" right={
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <Select label="Session" value={day} onChange={setDay} options={DAYS.map((d) => ({ value: d, label: fmtDate(d) }))} />
          <CTAButton icon={Play} onClick={run} disabled={busy}>{busy ? "Replaying..." : "Replay from raw"}</CTAButton>
        </div>
      } hint="Reads the files from disk, never from memory: a replay that reuses what it already read proves nothing.">
        {err && <Callout tone="critical" title="Replay refused">{err.message}</Callout>}
        {!result && !err && <p style={{ fontSize: 13, color: t.textMuted, margin: 0 }}>Choose a session and replay it. 14/10 has the bad print, the vendor clock fault and a feed gap.</p>}
        {result && (
          <>
            <Callout tone={result.all_match ? "good" : "critical"} title={result.all_match
              ? `Identical. ${result.files.length} files and ${result.partitions.length} partitions reproduced in ${fmtMs(result.wall_ms)}.`
              : "Mismatch: the replay does not reproduce the recorded output."}>
              Every raw file matched its pinned SHA-256, and every governed partition - trades, quotes and bars - matched the
              digest recorded by the run behind the current tables.
            </Callout>
            <Grid cols={2} min={420}>
              <Table
                columns={[
                  { key: "file", label: "Raw file", render: (r) => <Mono>{r.file}</Mono> },
                  { key: "rows", label: "Rows", align: "right", render: (r) => fmtInt(r.rows) },
                  { key: "match", label: "Pinned hash", render: (r) => r.match === null ? <Badge tone="neutral">no manifest</Badge> : <Badge tone={r.match ? "good" : "critical"}>{r.match ? "matches" : "differs"}</Badge> },
                ]}
                rows={result.files}
              />
              <Table
                columns={[
                  { key: "partition", label: "Governed partition", render: (r) => <Mono>{r.partition}</Mono> },
                  { key: "rows", label: "Rows", align: "right", render: (r) => fmtInt(r.rows) },
                  { key: "match", label: "Recorded digest", render: (r) => <Badge tone={r.match ? "good" : "critical"}>{r.match ? "matches" : "differs"}</Badge> },
                ]}
                rows={result.partitions}
              />
            </Grid>
          </>
        )}
      </Card>

      <SectionTitle>Restatement log</SectionTitle>
      <Callout tone="neutral" title="Decisions read bars as first published">
        A bar is published three seconds after its minute ends. Anything that arrives later - a straggler, a release from a
        hold, a vendor gap fill, an exchange cancel - restates the bar, and the restatement is logged here. The strategy
        and its backtests read the published version only: a backtest on restated bars uses information the desk did not
        have at the time.
      </Callout>
      <Card>
        <Table
          columns={[
            { key: "symbol", label: "Instrument", render: (r) => `${r.symbol || r.instrument_key}` },
            { key: "minute", label: "Minute", render: (r) => `${fmtDate(r.minute)} ${fmtTime(r.minute, { seconds: false })}` },
            { key: "pub_trades", label: "Trades, published to final", align: "right", render: (r) => `${fmtInt(r.pub_trades ?? 0)} to ${fmtInt(r.trades)}` },
            { key: "pub_close", label: "Close", align: "right", render: (r) => `${r.pub_close == null ? "none" : fmtNum(r.pub_close, 3)} to ${fmtNum(r.close, 3)}` },
            { key: "cause", label: "Why", wrap: true },
          ]}
          rows={data.restatements}
          empty="No bar was restated."
        />
      </Card>

      <SectionTitle>Run ledger</SectionTitle>
      <Card hint="Every run that produced the current tables, what triggered it, and what it cost at list price.">
        <Table
          columns={[
            { key: "run_id", label: "Run", render: (r) => <Mono>{r.run_id}</Mono> },
            { key: "kind", label: "Kind" },
            { key: "trigger", label: "Trigger", wrap: true },
            { key: "started_at", label: "Started", render: (r) => fmtDateTime(r.started_at) },
            { key: "contract_versions", label: "Contracts" },
            { key: "wall_ms", label: "Wall", align: "right", render: (r) => fmtMs(r.wall_ms) },
            { key: "cost_aud", label: "Compute", align: "right", render: (r) => fmtAud(r.cost_aud, { decimals: 5 }) },
            { key: "output_sha256", label: "Output digest", render: (r) => <Mono dim>{r.output_sha256.slice(0, 16)}</Mono> },
          ]}
          rows={data.runs}
        />
      </Card>
    </>
  );
}

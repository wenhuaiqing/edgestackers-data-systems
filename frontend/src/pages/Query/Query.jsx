// The query layer, open to anyone with the link: read-only SQL over the
// governed tables, behind a validator and a time limit.

import { useState } from "react";
import { Play } from "lucide-react";
import { useTheme } from "../../context/ThemeContext.jsx";
import { api, fmtMs } from "../../lib/api.js";
import { Button, CTAButton, Callout, Card, Grid, PageHeader, Table } from "../../lib/ui.jsx";

const EXAMPLES = [
  {
    label: "Feed latency by session",
    sql: `SELECT source, day,
       round(quantile_cont(epoch_ms(ts_received) - epoch_ms(ts_exchange_raw), 0.5), 1) AS p50_ms,
       round(quantile_cont(epoch_ms(ts_received) - epoch_ms(ts_exchange_raw), 0.99), 1) AS p99_ms,
       count(*) AS events
FROM trades
GROUP BY 1, 2
ORDER BY 1, 2`,
  },
  {
    label: "Every event behind one bar",
    sql: `SELECT source, trade_id, event_type, ts_exchange, ts_received, ts_available,
       price, qty, status, flags, file, raw_row
FROM trades
WHERE instrument_key = 'INS-013'
  AND date_trunc('minute', ts_exchange) = TIMESTAMP '2026-10-14 12:28:00'
ORDER BY ts_exchange`,
  },
  {
    label: "What the price band held",
    sql: `SELECT symbol, venue, ts_exchange, reason, resolution, resolved_at
FROM quarantine
WHERE check_id = 'price_band'`,
  },
  {
    label: "Live against shadow, by session",
    sql: `SELECT day,
       sum(pnl) FILTER (WHERE model_id = 'mr-v1') AS live_pnl,
       sum(pnl) FILTER (WHERE model_id = 'mr-v2') AS shadow_pnl,
       sum(orders) FILTER (WHERE model_id = 'mr-v1') AS live_orders
FROM pnl_daily
GROUP BY day
ORDER BY day`,
  },
  {
    label: "Orders the gate shaped",
    sql: `SELECT gate, reason, count(*) AS orders, round(sum(notional)) AS notional
FROM orders
WHERE model_id = 'mr-v1'
GROUP BY 1, 2
ORDER BY 3 DESC`,
  },
  {
    label: "Try something it refuses",
    sql: `SELECT * FROM read_csv('/etc/passwd')`,
  },
];

export default function Query() {
  const { t } = useTheme();
  const [sql, setSql] = useState(EXAMPLES[0].sql);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);

  const run = async (text = sql) => {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api("/api/query", { method: "POST", body: { sql: text } }));
    } catch (e) {
      setRes(null);
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Query layer"
        brief="Build dependable ingestion, storage and query layers for raw, changing event and trading data."
        subtitle="The governed tables are queryable by anyone with the link. SELECT only, against an allowlist of tables, with a row limit and a five-second ceiling. The database connection itself cannot read files or URLs, so the validator is the second layer, not the only one."
      />
      <Grid cols={2} min={420}>
        <Card title="Examples">
          <div style={{ display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
            {EXAMPLES.map((e) => (
              <Button key={e.label} onClick={() => { setSql(e.sql); run(e.sql); }}>{e.label}</Button>
            ))}
          </div>
          <p style={{ fontSize: 12, color: t.textMuted, margin: "14px 0 0", lineHeight: 1.5 }}>
            Tables: trades, quotes, quarantine, bars, book, gate, restatements, clock_offsets, raw_files,
            partition_hashes, orders, equity, pnl_daily, round_trips, kill_switch, incidents, ablation, instruments, runs,
            run_stages, contracts, contract_versions, model_registry, alerts. Timestamps are exchange-local (AEDT).
          </p>
        </Card>
        <Card title="SQL">
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            spellCheck={false}
            aria-label="SQL"
            style={{
              width: "100%", minHeight: 210, fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: 12.5,
              background: t.code, color: t.text, border: `1px solid ${t.border}`, borderRadius: 10, padding: 12,
              resize: "vertical", lineHeight: 1.5,
            }}
          />
          <div style={{ marginTop: 10, display: "flex", gap: 12, alignItems: "center" }}>
            <CTAButton icon={Play} onClick={() => run()} disabled={busy}>{busy ? "Running..." : "Run"}</CTAButton>
            {res && <span style={{ fontSize: 12, color: t.textMuted }}>{res.rows.length} rows in {fmtMs(res.ms)}</span>}
          </div>
        </Card>
      </Grid>
      {err && <Callout tone="critical" title="Refused">{err.message}</Callout>}
      {res && (
        <Card title="Result" hint={`Ran as: ${res.sql.replace(/\s+/g, " ").slice(0, 220)}`}>
          <Table
            maxHeight={520}
            columns={res.columns.map((c) => ({ key: c, label: c, render: (r) => r[c] === null ? "null" : typeof r[c] === "object" ? JSON.stringify(r[c]) : String(r[c]) }))}
            rows={res.rows}
            empty="No rows."
          />
        </Card>
      )}
    </>
  );
}

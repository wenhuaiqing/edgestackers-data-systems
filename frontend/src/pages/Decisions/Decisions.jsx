// Model outputs put to work: the live model trading through the quality
// gate, the shadow model beside it, and promotion decided by a rule agreed
// before the shadow run began.

import { useMemo, useState } from "react";
import { ArrowUpCircle } from "lucide-react";
import { Line, LineChart, ReferenceLine } from "recharts";
import { useTheme } from "../../context/ThemeContext.jsx";
import { apiWrite, fmtAud, fmtDay, fmtInt, fmtNum, fmtTime, pct, useApi } from "../../lib/api.js";
import {
  Badge, CTAButton, Callout, Card, ChartFrame, ErrorNote, Grid, KeyValues, Loading, Mono, PageHeader,
  SectionTitle, Select, Stat, Table, useChartParts,
} from "../../lib/ui.jsx";

const DAYS = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"];

function Promotion({ promotion, onDone }) {
  const { t } = useTheme();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const promote = async () => {
    setBusy(true);
    try {
      const r = await apiWrite(`/api/models/${promotion.shadow}/promote`);
      setMsg({ tone: "good", text: `${r.model_id} is live ${r.effective}.` });
      onDone();
    } catch (e) {
      setMsg({ tone: "critical", text: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title={`Promote ${promotion.shadow} to live?`} right={<Badge tone={promotion.eligible ? "good" : "neutral"}>{promotion.eligible ? "eligible" : "not eligible"}</Badge>}>
      <p style={{ fontSize: 13, margin: "0 0 10px", lineHeight: 1.55 }}>{promotion.rule}</p>
      <Table
        columns={[
          { key: "rule", label: "Rule", wrap: true },
          { key: "value", label: "Measured", align: "right", render: (r) => typeof r.value === "number" && Math.abs(r.value) > 100 ? fmtAud(r.value, { signed: true }) : String(r.value) },
          { key: "passed", label: "", render: (r) => <Badge tone={r.passed ? "good" : "critical"}>{r.passed ? "met" : "not met"}</Badge> },
        ]}
        rows={promotion.checks}
      />
      <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <CTAButton icon={ArrowUpCircle} onClick={promote} disabled={busy}>Promote {promotion.shadow}</CTAButton>
        <span style={{ fontSize: 12, color: t.textMuted }}>The server applies the rule, not the button. Ahead in total is not the same as ahead.</span>
      </div>
      {msg && <div style={{ marginTop: 12 }}><Callout tone={msg.tone} title={msg.tone === "good" ? "Promoted" : "Refused"}>{msg.text}</Callout></div>}
    </Card>
  );
}

export default function Decisions() {
  const { t } = useTheme();
  const chart = useChartParts();
  const { data, error, reload } = useApi("/api/decisions");
  const [day, setDay] = useState("2026-10-14");
  const [symbol, setSymbol] = useState("");
  const { data: orders } = useApi(`/api/orders?day=${day}${symbol ? `&instrument=${symbol}` : ""}&limit=300`);

  const curve = useMemo(() => {
    if (!data) return [];
    // Each session's equity starts at zero; chain them into one week.
    const by = {};
    for (const r of data.desk) {
      by[r.minute] ??= { minute: r.minute };
      by[r.minute][r.model_id] = r.equity;
    }
    const rows = Object.values(by).sort((a, b) => a.minute.localeCompare(b.minute));
    const carry = { "mr-v1": 0, "mr-v2": 0 };
    let prevDay = null;
    const last = { "mr-v1": 0, "mr-v2": 0 };
    return rows.map((r) => {
      const d = r.minute.slice(0, 10);
      if (prevDay && d !== prevDay) { carry["mr-v1"] += last["mr-v1"]; carry["mr-v2"] += last["mr-v2"]; }
      prevDay = d;
      last["mr-v1"] = r["mr-v1"] ?? last["mr-v1"];
      last["mr-v2"] = r["mr-v2"] ?? last["mr-v2"];
      return { label: `${fmtDay(r.minute)} ${fmtTime(r.minute, { seconds: false })}`, live: carry["mr-v1"] + last["mr-v1"], shadow: carry["mr-v2"] + last["mr-v2"] };
    });
  }, [data]);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const tot = (m) => data.pnl_daily.filter((r) => r.model_id === m).reduce((a, r) => a + r.pnl, 0);
  const trips = Object.fromEntries(data.round_trips.map((r) => [r.model_id, r]));
  const live = data.models.find((m) => m.stage === "live");
  const shadow = data.models.find((m) => m.stage === "shadow");
  const days = data.pnl_daily.filter((r) => r.model_id === "mr-v1").map((r) => {
    const s = data.pnl_daily.find((x) => x.model_id === "mr-v2" && x.day === r.day);
    return { day: r.day, live: r.pnl, shadow: s?.pnl, live_orders: r.orders, live_dd: r.max_drawdown, shadow_dd: s?.max_drawdown, costs: r.costs };
  });

  return (
    <>
      <PageHeader
        title="Decisions & models"
        brief="Put decision workflows and model outputs to work in production."
        subtitle="A deliberately plain short-horizon mean-reversion strategy on the consolidated one-minute bars - the point is not the strategy, but that a strategy is a consumer of the data with its own failure modes. It trades through the quality gate, sees bars only as first published, and runs under a desk loss limit. A shadow model runs beside it on the same data and trades nothing."
      />
      <Grid cols={4} min={200}>
        <Stat label={`Live (${live?.model_id})`} value={fmtAud(tot("mr-v1"))} sub={`${fmtInt(trips["mr-v1"]?.trips)} round trips, ${pct(trips["mr-v1"]?.hit_rate, 0)} profitable`} emphasis />
        <Stat label={`Shadow (${shadow?.model_id || "mr-v2"})`} value={fmtAud(tot("mr-v2"))} sub={`${fmtInt(trips["mr-v2"]?.trips)} round trips, ${pct(trips["mr-v2"]?.hit_rate, 0)} profitable`} />
        <Stat label="Desk loss limit" value={fmtAud(data.limits.desk_loss_limit)} sub={data.kill_switch.length ? `fired ${data.kill_switch.length} time(s)` : "never reached this week"} />
        <Stat label="Unit size" value={fmtAud(data.limits.unit_notional)} sub={`${data.limits.brokerage_bp} bp brokerage; max hold ${data.limits.max_hold_minutes} min`} />
      </Grid>

      <Card title="Desk equity through the week" hint="Marked to market each minute on published prices; each session ends flat. Synthetic market - the edge is the one the generator put there.">
        <ChartFrame height={280}>
          <LineChart data={curve} margin={{ left: 8, right: 12, top: 8 }}>
            {chart.grid}
            {chart.xAxis({ dataKey: "label", interval: 359, tickFormatter: (v) => v.split(" ").slice(0, 2).join(" ") })}
            {chart.yAxis({ tickFormatter: (v) => `${v < 0 ? "-" : ""}$${Math.abs(v / 1000).toFixed(0)}k` })}
            {chart.tooltip({ formatter: (v, n) => [fmtAud(v), n] })}
            {chart.legend()}
            <ReferenceLine y={0} stroke={t.borderBright} />
            <Line dataKey="live" name="Live mr-v1" stroke={t.series[0]} dot={false} strokeWidth={1.7} isAnimationActive={false} />
            <Line dataKey="shadow" name="Shadow mr-v2" stroke={t.series[1]} dot={false} strokeWidth={1.3} isAnimationActive={false} />
          </LineChart>
        </ChartFrame>
      </Card>
      <div style={{ height: 14 }} />

      <Grid cols={2} min={440}>
        <Card title="By session">
          <Table
            columns={[
              { key: "day", label: "Session", render: (r) => fmtDay(r.day) },
              { key: "live", label: "Live", align: "right", render: (r) => fmtAud(r.live) },
              { key: "shadow", label: "Shadow", align: "right", render: (r) => <span style={{ color: r.shadow > r.live ? t.status.good : t.text }}>{fmtAud(r.shadow)}</span> },
              { key: "live_dd", label: "Live drawdown", align: "right", render: (r) => fmtAud(r.live_dd) },
              { key: "live_orders", label: "Live orders", align: "right", render: (r) => fmtInt(r.live_orders) },
              { key: "costs", label: "Brokerage", align: "right", render: (r) => fmtAud(r.costs) },
            ]}
            rows={days}
          />
          <p style={{ fontSize: 12, color: t.textMuted, margin: "8px 0 0" }}>
            15/10 and 16/10 trade at half size: ALT's trades are quarantined by its contract, so the gate degrades every
            instrument until someone decides the contract change on Feeds & contracts.
          </p>
        </Card>
        {data.promotion && <Promotion promotion={data.promotion} onDone={reload} />}
      </Grid>

      <SectionTitle>How the gate shaped the orders</SectionTitle>
      <Grid cols={2} min={440}>
        <Card title="Minutes not fully open, by session and reason">
          <Table
            maxHeight={300}
            columns={[
              { key: "day", label: "Session", render: (r) => fmtDay(r.day) },
              { key: "state", label: "Gate", render: (r) => <Badge tone={r.state === "blocked" ? "critical" : "warning"}>{r.state}</Badge> },
              { key: "reason", label: "Why", wrap: true },
              { key: "minutes", label: "Instrument-minutes", align: "right", render: (r) => fmtInt(r.minutes) },
            ]}
            rows={data.gate_days}
          />
        </Card>
        <Card title="Orders by the gate state they were decided under">
          <Table
            maxHeight={300}
            columns={[
              { key: "model_id", label: "Model" },
              { key: "gate", label: "Gate", render: (r) => <Badge tone={r.gate === "open" ? "good" : r.gate === "blocked" ? "critical" : "warning"}>{r.gate}</Badge> },
              { key: "reason", label: "Order" },
              { key: "n", label: "Orders", align: "right", render: (r) => fmtInt(r.n) },
            ]}
            rows={data.gate_orders}
          />
        </Card>
      </Grid>

      <Grid cols={2} min={440}>
        <Card title="Model registry">
          {data.models.map((m) => (
            <div key={m.model_id} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                <Mono>{m.model_id}</Mono>
                <Badge tone={m.stage === "live" ? "good" : m.stage === "shadow" ? "ai" : "neutral"}>{m.stage}</Badge>
              </div>
              <p style={{ fontSize: 12.5, margin: 0, color: t.textMuted, lineHeight: 1.5 }}>{m.description}</p>
            </div>
          ))}
          <KeyValues items={[
            ["Execution", "next minute's consolidated book: buy at the ask, sell at the bid"],
            ["Point in time", "bars as first published, never restated"],
          ]} />
        </Card>
        <Card title="Orders" right={
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Select label="Session" value={day} onChange={setDay} options={DAYS.map((d) => ({ value: d, label: fmtDay(d) }))} />
            <Select label="Instrument" value={symbol} onChange={setSymbol} options={[{ value: "", label: "All" }, ...["INS-013", "INS-011", "INS-009", "INS-017"].map((i) => ({ value: i, label: i }))]} />
          </div>
        }>
          <Table
            maxHeight={330}
            columns={[
              { key: "symbol", label: "Instrument" },
              { key: "executed_at", label: "Executed", render: (r) => fmtTime(r.executed_at, { seconds: false }) },
              { key: "side", label: "Side" },
              { key: "qty", label: "Qty", align: "right", render: (r) => fmtInt(r.qty) },
              { key: "price", label: "Price", align: "right", render: (r) => fmtNum(r.price, 3) },
              { key: "reason", label: "Reason" },
              { key: "gate", label: "Gate", render: (r) => r.gate === "open" ? "open" : <Badge tone="warning">{r.gate}</Badge> },
            ]}
            rows={orders || []}
          />
        </Card>
      </Grid>
    </>
  );
}

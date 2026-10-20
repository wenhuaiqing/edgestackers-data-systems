// Shared page furniture. Pages compose these so layout and chart conventions
// are decided once: recessive grid and axes, a legend whenever there is more
// than one series, status carried by label as well as colour, and a table view
// available wherever a chart could be misread.

import { useEffect, useRef, useState } from "react";
import {
  CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useTheme } from "../context/ThemeContext.jsx";

// Width of the box a component is sitting in, not the window.
//
// The window is the wrong question twice over: the desktop mobile preview is
// a 390px frame inside a 1600px window, and a card in a three-up row is
// narrow on a wide screen. Everything that needs to adapt asks its own
// container.
function useContainerWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

// One place to decide what "a phone" means for layout.
const PHONE = 480;

export function PageHeader({ title, subtitle, right, brief }) {
  // `brief` quotes the line of the job advertisement this page answers.
  const { t } = useTheme();
  const [ref, width] = useContainerWidth();
  const phone = width !== null && width < PHONE;
  // On a 667px-tall phone the heading and a five-line intro were taking most
  // of the screen before a single number appeared. The words still matter -
  // they are what make the figures mean something - so the intro collapses to
  // its first sentence with the rest a tap away, rather than being cut.
  const [open, setOpen] = useState(false);
  const full = typeof subtitle === "string" ? subtitle : null;
  const firstStop = full ? full.indexOf(". ") : -1;
  const canTrim = phone && firstStop > 40 && firstStop < full.length - 20;
  const shown = canTrim && !open ? `${full.slice(0, firstStop + 1)}` : subtitle;
  return (
    <div ref={ref} style={{
      display: "flex", alignItems: "flex-start", justifyContent: "space-between",
      gap: phone ? 10 : 16, marginBottom: phone ? 12 : 18, flexWrap: "wrap",
    }}>
      <div style={{ minWidth: 0 }}>
        <h1 style={{
          margin: 0, fontSize: phone ? 19 : 22, fontWeight: 700,
          letterSpacing: "-0.02em", color: t.text,
        }}>
          {title}
        </h1>
        {brief && (
          // The line of the advertisement this page answers. Quoted, so a
          // reader with the ad open in the next tab sees the match at once.
          <p style={{
            margin: "6px 0 0", fontSize: 11.5, color: t.accent, fontWeight: 600,
            lineHeight: 1.45, maxWidth: 760,
          }}>
            <span style={{ textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 10.5, marginRight: 6 }}>From the brief</span>
            <span style={{ color: t.textMuted, fontWeight: 500, fontStyle: "italic" }}>"{brief}"</span>
          </p>
        )}
        {subtitle && (
          <p style={{
            margin: phone ? "4px 0 0" : "6px 0 0",
            fontSize: phone ? 12.5 : 13,
            color: t.textMuted, maxWidth: 760, lineHeight: 1.45,
          }}>
            {shown}
            {canTrim && (
              <button
                onClick={() => setOpen((v) => !v)}
                style={{
                  border: "none", background: "none", padding: "0 0 0 6px",
                  color: t.accent, font: "inherit", fontWeight: 600, cursor: "pointer",
                }}
              >
                {open ? "less" : "more"}
              </button>
            )}
          </p>
        )}
      </div>
      {right}
    </div>
  );
}

// The primary action on a page. One of these per page at most: a second
// filled button competes with the first and neither reads as the thing to do.
//
// The hover is a change of fill, not a dim or a shadow, so the affordance
// survives a shared screen at whatever the viewer's compression does to it.
export function CTAButton({ onClick, icon: Icon, children, style, disabled }) {
  const { t } = useTheme();
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      style={{
        display: "inline-flex", alignItems: "center", gap: 7,
        background: hover ? t.ctaHoverBg : t.ctaBg,
        color: hover ? t.ctaHoverText : t.ctaText,
        border: "none", borderRadius: 999, padding: "9px 16px",
        fontSize: 12.5, fontWeight: 700, cursor: disabled ? "wait" : "pointer",
        fontFamily: "inherit", opacity: disabled ? 0.6 : 1,
        transition: "background-color .15s ease, color .15s ease",
        ...style,
      }}
    >
      {Icon && <Icon size={14} />}
      {children}
    </button>
  );
}

export function Card({ title, hint, children, right, pad = 16, rule = true, style }) {
  const { t } = useTheme();
  return (
    <section style={{
      background: t.surface,
      border: `1px solid ${t.border}`,
      // A hairline along the top edge: enough to make a row of cards read as
      // one band, not enough to compete with the chart inside.
      borderTop: rule ? `2px solid ${t.cardRule}` : `1px solid ${t.border}`,
      borderRadius: 12,
      padding: pad,
      minWidth: 0,
      height: "100%",
      display: "flex",
      flexDirection: "column",
      ...style,
    }}>
      {(title || right) && (
        <header style={{
          display: "flex", alignItems: "baseline", justifyContent: "space-between",
          gap: 12, marginBottom: hint ? 4 : 12,
        }}>
          <h2 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: t.text, letterSpacing: "-0.01em" }}>
            {title}
          </h2>
          {right}
        </header>
      )}
      {hint && (
        <p style={{ margin: "0 0 12px", fontSize: 12, color: t.textMuted, lineHeight: 1.5 }}>{hint}</p>
      )}
      {children}
    </section>
  );
}

export function Grid({ cols = 2, gap = 14, children, min = 320 }) {
  return (
    <div style={{
      display: "grid",
      // min is the width a card wants on a desktop. Used raw it also decides
      // the phone: a 220px minimum in a 347px column is one card per row, so
      // four stat tiles became four full-width bands and a 667px screen showed
      // three of them and nothing else.
      //
      // The clamp lets a narrow container fall back to roughly half its own
      // width - two tiles across a phone - while a wide one still gets the
      // intended card size. Pure CSS, so it needs no measuring and cannot
      // disagree with what the browser actually did.
      //
      // That suits stat tiles. A card that wants 300px or more is a chart or a
      // table, and two of those across a phone are two unreadable halves, so
      // those take the full width instead.
      gridTemplateColumns: min >= 300
        ? `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))`
        : `repeat(auto-fit, minmax(clamp(132px, 46%, ${min}px), 1fr))`,
      gap,
      // Stretch, not start: cards in a row share a height so the row reads as
      // one band. Card and Stat both fill it, so a short table no longer
      // leaves a ragged edge beside a tall chart.
      alignItems: "stretch",
      marginBottom: gap,
    }}>
      {children}
    </div>
  );
}

// A headline number is not a chart. Used where the job is a single magnitude.
export function Stat({ label, value, sub, tone, emphasis = false }) {
  const { t } = useTheme();
  const [ref, width] = useContainerWidth();
  // Two tiles across a phone means each is about 165px. The desktop type and
  // padding do not fit that, so they step down with the tile.
  const tight = width !== null && width < 210;
  // The headline stat on a page is a filled brand tile, so the eye lands
  // somewhere deliberate. A status tone always wins over the fill: a critical
  // number must not be dressed as the hero of the page.
  const hero = emphasis && !tone;
  const colour = tone ? t.status[tone] : hero ? t.statHeroText : t.text;
  const muted = hero ? t.statHeroMuted : t.textMuted;
  return (
    <div ref={ref} style={{
      background: hero ? t.statHeroBg : t.surface,
      border: `1px solid ${tone || hero ? "transparent" : t.border}`,
      outline: tone ? `1px solid ${t.status[tone]}33` : "none",
      borderRadius: 12,
      padding: tight ? "11px 12px" : "14px 16px",
      minWidth: 0,
      height: "100%",
    }}>
      <div style={{
        fontSize: tight ? 10 : 11, color: muted, fontWeight: 600,
        letterSpacing: "0.04em", textTransform: "uppercase",
        marginBottom: tight ? 4 : 6, lineHeight: 1.3,
      }}>
        {label}
      </div>
      <div style={{
        fontSize: tight ? (emphasis ? 23 : 20) : (emphasis ? 30 : 24),
        fontWeight: 700, color: colour,
        letterSpacing: "-0.02em", lineHeight: 1.1,
        // A long figure in a 165px tile has to be allowed to break rather
        // than push the tile wider than its column.
        overflowWrap: "anywhere",
      }}>
        {value}
      </div>
      {sub && (
        <div style={{
          fontSize: tight ? 11 : 12, color: muted,
          marginTop: tight ? 4 : 6, lineHeight: 1.35,
        }}>
          {sub}
        </div>
      )}
    </div>
  );
}

// Status always ships with its label - never colour alone.
export function Badge({ tone = "good", children }) {
  const { t } = useTheme();
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      background: t.statusBg[tone], color: t.status[tone],
      border: `1px solid ${t.status[tone]}33`,
      borderRadius: 999, padding: "2px 9px",
      fontSize: 11, fontWeight: 700, whiteSpace: "nowrap",
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: 999,
        background: t.status[tone], flexShrink: 0,
      }} />
      {children}
    </span>
  );
}

// A row as a card: the first column is the heading, the rest become labelled
// pairs. Sideways scrolling inside a card is the worst of both - the reader
// cannot see the row and cannot see the column headings either, so on a phone
// a wide table stops being a table.
function RowCard({ columns, row, onClick }) {
  const { t } = useTheme();
  const [head, ...rest] = columns;
  const value = (c) => (c.render ? c.render(row) : row[c.key]);
  const shown = rest.filter((c) => {
    const v = value(c);
    return v !== null && v !== undefined && v !== "" && v !== "—";
  });
  return (
    <div
      onClick={onClick}
      style={{
        border: `1px solid ${t.border}`, borderRadius: 10,
        padding: "10px 12px", background: t.surface,
        cursor: onClick ? "pointer" : "default",
      }}
    >
      <div style={{
        fontSize: 13, fontWeight: 700, color: t.text,
        marginBottom: shown.length ? 8 : 0, lineHeight: 1.35,
      }}>
        {value(head)}
      </div>
      <div style={{ display: "grid", gap: 5 }}>
        {shown.map((c) => (
          <div key={c.key} style={{
            display: "flex", alignItems: "baseline", justifyContent: "space-between",
            gap: 12, fontSize: 12.5,
          }}>
            <span style={{
              color: t.textMuted, fontSize: 11, fontWeight: 600,
              letterSpacing: "0.03em", textTransform: "uppercase",
              whiteSpace: "nowrap", flexShrink: 0,
            }}>
              {c.label}
            </span>
            <span style={{
              color: t.text, textAlign: "right", minWidth: 0,
              fontVariantNumeric: c.align === "right" ? "tabular-nums" : "normal",
            }}>
              {value(c)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// A segmented control that wraps rather than clips.
//
// Every one of these was an inline-flex with overflow:hidden, which on a
// phone did not crop the last option so much as delete it: "Due within 30
// days" was unreachable on Compliance at 390px, with nothing on screen to
// suggest an option was missing. Wrapping keeps every option reachable at any
// width, at the cost of the joined-segment look when it has to go to two
// lines - which is the right trade, because an option you cannot see is not a
// smaller problem than a seam.
export function SegmentedControl({ options, value, onChange, label }) {
  const { t } = useTheme();
  return (
    <div role="group" aria-label={label} style={{ display: "flex", flexWrap: "wrap", gap: 4, minWidth: 0 }}>
      {options.map((o) => {
        const key = typeof o === "string" ? o : o.value;
        const text = typeof o === "string" ? o : o.label;
        const on = key === value;
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            aria-pressed={on}
            style={{
              border: `1px solid ${on ? t.accent : t.border}`,
              background: on ? t.accent : "transparent",
              color: on ? t.accentText : t.textMuted,
              // The font shorthand first: placed after fontSize it silently
              // reset the size to the inherited 16px.
              font: "inherit", fontFamily: "inherit",
              borderRadius: 999, padding: "4px 12px",
              fontSize: 11.5, fontWeight: 700, whiteSpace: "nowrap",
              cursor: "pointer", lineHeight: 1.6,
            }}
          >
            {text}
          </button>
        );
      })}
    </div>
  );
}

export function Table({ columns, rows, empty = "Nothing to show.", maxHeight = 420, onRowClick }) {
  const { t } = useTheme();
  // Measured on the container, not the window: the mobile preview on a
  // desktop is a narrow box in a wide window, and a media query would call
  // that wide and lay out eight columns in 390px.
  //
  // And measured against what the table actually needs, not a guess from the
  // column count. The first version of this used 96px per column, which put a
  // four-column table's threshold at 384 - the Source systems table has a
  // 386px container and so stayed a table by two pixels, then overflowed its
  // container by sixty-one. The table's own natural width is the only honest
  // number, so it is remembered from whenever the table last rendered wide
  // and compared with the space available from then on.
  const wrapRef = useRef(null);
  const tableRef = useRef(null);
  const naturalWidth = useRef(0);
  const [narrow, setNarrow] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const measure = () => {
      // The wrapper, not the table: the table carries width:100%, so its own
      // scrollWidth never exceeds its box no matter how badly the nowrap
      // cells overflow. The wrapper is where the overflow actually shows.
      if (tableRef.current) {
        naturalWidth.current = Math.max(naturalWidth.current, el.scrollWidth);
      }
      // Until the table has been seen at its natural width there is nothing to
      // compare, so the first paint is a table and the observer corrects it.
      //
      // Hysteresis: switching layout changes the wrapper's own scrollbar, and
      // so its width. Without a margin, a table within a few pixels of fitting
      // flipped between the two layouts on every render until React stopped it.
      const natural = naturalWidth.current;
      if (natural) setNarrow((was) => (was ? natural > el.clientWidth - 24 : natural > el.clientWidth + 1));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  });

  if (!rows?.length) {
    return (
      <div ref={wrapRef}>
        <p style={{ fontSize: 13, color: t.textMuted, margin: "8px 0" }}>{empty}</p>
      </div>
    );
  }

  if (narrow) {
    return (
      <div ref={wrapRef} style={{ overflow: "auto", maxHeight, display: "grid", gap: 8 }}>
        {rows.map((r, i) => (
          <RowCard
            key={r._key ?? i}
            columns={columns}
            row={r}
            onClick={onRowClick ? () => onRowClick(r) : undefined}
          />
        ))}
      </div>
    );
  }

  return (
    <div ref={wrapRef} style={{ overflow: "auto", maxHeight, border: `1px solid ${t.border}`, borderRadius: 10 }}>
      <table ref={tableRef} style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} style={{
                position: "sticky", top: 0, zIndex: 1,
                background: t.tableHead,
                textAlign: c.align || "left",
                padding: "9px 12px",
                fontWeight: 700, fontSize: 11,
                color: t.textMuted,
                letterSpacing: "0.04em", textTransform: "uppercase",
                borderBottom: `1px solid ${t.border}`,
                whiteSpace: "nowrap",
              }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r._key ?? i}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              style={{
                borderBottom: `1px solid ${t.rowDivider}`,
                cursor: onRowClick ? "pointer" : "default",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = t.rowHover; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
            >
              {columns.map((c) => (
                <td key={c.key} style={{
                  padding: "8px 12px",
                  textAlign: c.align || "left",
                  color: t.text,
                  whiteSpace: c.wrap ? "normal" : "nowrap",
                  fontVariantNumeric: c.align === "right" ? "tabular-nums" : "normal",
                }}>
                  {c.render ? c.render(r) : r[c.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Chart chrome: recessive grid, thin axes, shared tooltip styling.
export function ChartFrame({ height = 260, children }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  );
}

export function useChartParts() {
  const { t } = useTheme();
  const axis = {
    stroke: t.textDim,
    tick: { fill: t.textMuted, fontSize: 11 },
    tickLine: false,
    axisLine: { stroke: t.grid },
  };
  return {
    t,
    grid: <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />,
    xAxis: (props) => <XAxis {...axis} {...props} />,
    yAxis: (props) => <YAxis {...axis} width={62} {...props} />,
    tooltip: (props) => (
      <Tooltip
        cursor={{ stroke: t.borderBright, strokeWidth: 1 }}
        contentStyle={{
          background: t.surface,
          border: `1px solid ${t.borderBright}`,
          borderRadius: 10,
          fontSize: 12,
          color: t.text,
          boxShadow: "0 8px 24px rgba(0,0,0,0.10)",
        }}
        labelStyle={{ color: t.textMuted, fontWeight: 600, marginBottom: 4 }}
        {...props}
      />
    ),
    legend: (props) => (
      <Legend
        wrapperStyle={{ fontSize: 11.5, color: t.textMuted, paddingTop: 8 }}
        iconType="plainline"
        iconSize={14}
        {...props}
      />
    ),
  };
}

// Toggle between a chart and the numbers behind it. Required wherever a
// contrast warning or a dense series could make the chart alone misleading.
export function ChartOrTable({ chart, table, defaultView = "chart" }) {
  const { t } = useTheme();
  const [view, setView] = useState(defaultView);
  return (
    <>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
        <SegmentedControl
          label="Chart or table"
          options={[{ value: "chart", label: "Chart" }, { value: "table", label: "Table" }]}
          value={view}
          onChange={setView}
        />
      </div>
      {view === "chart" ? chart : table}
    </>
  );
}

export function Loading({ label = "Loading" }) {
  const { t } = useTheme();
  return <p style={{ fontSize: 13, color: t.textMuted, padding: "18px 0" }}>{label}…</p>;
}

export function ErrorNote({ error }) {
  const { t } = useTheme();
  if (!error) return null;
  return (
    <div style={{
      background: t.statusBg.critical, color: t.status.critical,
      border: `1px solid ${t.status.critical}33`, borderRadius: 10,
      padding: "10px 14px", fontSize: 12.5, marginBottom: 14,
    }}>
      {String(error.message || error)}
    </div>
  );
}

export function pct(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function signedPct(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const v = Number(value) * 100;
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

// A secondary action: outlined, so it never competes with the page's CTA.
export function Button({ onClick, icon: Icon, children, disabled, tone }) {
  const { t } = useTheme();
  const colour = tone === "ai" ? t.accent2 : t.accent;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        background: "transparent", color: colour, border: `1px solid ${colour}`,
        borderRadius: 999, padding: "6px 13px", fontSize: 12, fontWeight: 650,
        cursor: disabled ? "wait" : "pointer", fontFamily: "inherit", opacity: disabled ? 0.55 : 1,
      }}
    >
      {Icon && <Icon size={13} />}
      {children}
    </button>
  );
}

// A paragraph that matters more than the ones around it: the finding, the
// refusal, the caveat. Tone says which.
export function Callout({ tone = "neutral", title, children }) {
  const { t } = useTheme();
  return (
    <div style={{
      background: t.statusBg[tone], borderLeft: `3px solid ${t.status[tone]}`,
      borderRadius: 10, padding: "11px 14px", fontSize: 13, lineHeight: 1.55, color: t.text, marginBottom: 14,
    }}>
      {title && <div style={{ fontWeight: 700, marginBottom: 3, color: t.status[tone] }}>{title}</div>}
      {children}
    </div>
  );
}

export function Mono({ children, dim }) {
  const { t } = useTheme();
  return (
    <span style={{
      fontFamily: "'JetBrains Mono', ui-monospace, monospace", fontSize: "0.92em",
      color: dim ? t.textMuted : t.text, background: t.code, borderRadius: 4, padding: "1px 5px",
      overflowWrap: "anywhere",
    }}>{children}</span>
  );
}

// Label-value pairs: a record's detail without a table.
export function KeyValues({ items, columns = 2 }) {
  const { t } = useTheme();
  return (
    <dl style={{
      display: "grid", gridTemplateColumns: `repeat(auto-fit, minmax(clamp(150px, 45%, ${columns > 2 ? 200 : 260}px), 1fr))`,
      gap: "10px 18px", margin: 0,
    }}>
      {items.filter(Boolean).map(([k, v]) => (
        <div key={k} style={{ minWidth: 0 }}>
          <dt style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: "0.05em", textTransform: "uppercase", color: t.textMuted }}>{k}</dt>
          <dd style={{ margin: "3px 0 0", fontSize: 13, color: t.text, overflowWrap: "anywhere" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SectionTitle({ children, right }) {
  const { t } = useTheme();
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, margin: "22px 0 10px" }}>
      <h2 style={{ margin: 0, fontSize: 14.5, fontWeight: 700, color: t.text }}>{children}</h2>
      {right}
    </div>
  );
}

export function Select({ value, onChange, options, label }) {
  const { t } = useTheme();
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: t.textMuted }}>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} style={{
        background: t.surface, color: t.text, border: `1px solid ${t.border}`, borderRadius: 8,
        padding: "5px 8px", fontSize: 12.5, fontFamily: "inherit",
      }}>
        {options.map((o) => {
          const v = typeof o === "string" ? o : o.value;
          return <option key={v} value={v}>{typeof o === "string" ? o : o.label}</option>;
        })}
      </select>
    </label>
  );
}

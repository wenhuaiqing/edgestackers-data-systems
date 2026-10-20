// Fetch helpers and formatters. Errors carry the server's own reason, because
// on this platform the reason for a refusal is the point.

import { useCallback, useEffect, useState } from "react";
import { API_BASE_URL, actorName, authHeaders } from "../config.js";

export async function api(path, { method = "GET", body, signal } = {}) {
  const opts = { method, headers: { Accept: "application/json", ...authHeaders() }, signal };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${API_BASE_URL}${path}`, opts);
  let payload = null;
  try { payload = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = payload?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => d.msg).join("; ")
      : `HTTP ${res.status} ${res.statusText}`;
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return payload;
}

// Mutating calls: every write site greppable, the actor applied in one place.
export function apiWrite(path, body = {}) {
  return fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json", "X-Actor": actorName(), ...authHeaders() },
    body: JSON.stringify(body),
  }).then(async (res) => {
    let payload = null;
    try { payload = await res.json(); } catch { /* empty */ }
    if (!res.ok) {
      const err = new Error(typeof payload?.detail === "string" ? payload.detail : `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    return payload;
  });
}

// Load-on-mount with a reload handle.
export function useApi(path) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) return undefined;
    const ctl = new AbortController();
    setError(null);
    api(path, { signal: ctl.signal }).then(setData).catch((e) => {
      if (e.name !== "AbortError") setError(e);
    });
    return () => ctl.abort();
  }, [path, tick]);
  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, reload };
}

export function fmtAud(value, { decimals = 0, short = false, signed = false } = {}) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const v = Number(value);
  const sign = v < 0 ? "-" : signed && v > 0 ? "+" : "";
  const a = Math.abs(v);
  if (short && a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(2)}M`;
  if (short && a >= 10_000) return `${sign}$${(a / 1_000).toFixed(1)}k`;
  return `${sign}$${a.toLocaleString("en-AU", { maximumFractionDigits: decimals, minimumFractionDigits: decimals })}`;
}

export function fmtInt(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-AU", { maximumFractionDigits: 0 });
}

export function fmtNum(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("en-AU", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function parse(value) {
  if (!value) return null;
  // Timestamps from the platform are exchange-local and carry no zone; read
  // them as written rather than letting the browser shift them.
  const s = String(value).replace(" ", "T");
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?/);
  if (!m) return null;
  return { y: m[1], mo: m[2], d: m[3], h: m[4], mi: m[5], s: m[6], f: m[7] };
}

export function fmtDate(value) {
  const p = parse(value);
  return p ? `${p.d}/${p.mo}/${p.y}` : "-";
}

export function fmtDay(value) {
  const p = parse(value);
  if (!p) return "-";
  const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const dow = new Date(Number(p.y), Number(p.mo) - 1, Number(p.d)).getDay();
  return `${names[dow]} ${p.d}/${p.mo}`;
}

export function fmtTime(value, { ms = false, seconds = true } = {}) {
  const p = parse(value);
  if (!p || !p.h) return "-";
  let out = `${p.h}:${p.mi}`;
  if (seconds) out += `:${p.s || "00"}`;
  if (ms) out += `.${(p.f || "000").slice(0, 3)}`;
  return out;
}

export function fmtDateTime(value, opts) {
  return `${fmtDate(value)} ${fmtTime(value, opts)}`;
}

export function fmtMs(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const v = Number(value);
  if (Math.abs(v) >= 10_000) return `${(v / 1000).toFixed(1)} s`;
  if (Math.abs(v) >= 100) return `${Math.round(v).toLocaleString("en-AU")} ms`;
  return `${v.toFixed(1)} ms`;
}

export function fmtDuration(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "-";
  const s = Number(seconds);
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  if (m < 60) return r ? `${m} min ${r} s` : `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function pct(value, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export const SOURCE_LABEL = { PRIMARY: "PRIMARY direct", ALT: "ALT direct", VENDOR: "Vendor copy of PRIMARY", REF: "Reference data" };

export const CHECK_LABEL = {
  schema: "Contract schema",
  duplicate_trade_id: "Duplicate trade id",
  negative_latency: "Negative latency",
  clock_offset: "Clock offset",
  feed_gap: "Feed gap",
  price_band: "Price band",
  cancel_applied: "Exchange cancels",
  crossed_book: "Crossed book",
  symbol_known: "Symbol known",
  watermark: "Watermark",
};

export const CONTROL_LABEL = {
  dedupe: "Dedupe by trade id",
  cancel_processing: "Exchange cancels",
  price_band: "Price band",
  clock_offset: "Clock offset correction",
  feed_arbitration: "Feed arbitration",
  crossed_book_filter: "Crossed-book filter",
  symbol_master: "Dated symbol master",
  quality_gate: "Quality gate",
  all_controls_off: "Every control off",
};

export const CATEGORY_LABEL = {
  duplicate_resend: "Duplicate resend",
  feed_gap: "Feed gap",
  venue_halt: "Venue halt",
  clock_skew: "Clock skew",
  bad_print: "Bad print",
  genuine_move: "Genuine move",
  schema_drift: "Schema drift",
  crossed_book: "Crossed book",
  late_reference_data: "Late reference data",
  unknown: "Unknown",
};

export const ACTION_LABEL = {
  dedupe_keep_first: "Dedupe, keep the first copy",
  fill_from_backup_feed: "Fill from the backup feed",
  apply_measured_offset: "Apply the measured offset",
  hold_and_await_cancel: "Hold and await the cancel",
  no_action: "No action",
  propose_contract_version: "Propose a contract version",
  exclude_quotes: "Exclude the quotes",
  hold_until_reference_arrives: "Hold until the reference data arrives",
  escalate_to_human: "Escalate to a person",
};

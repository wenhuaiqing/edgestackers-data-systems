// Auto-discovers pages under src/pages/<Section>/<Page>.jsx. The folder name
// becomes the URL slug; MODULE_META fixes the label, icon, group and order.
//
// The groups follow the advertisement's "What you will own", so reading the
// nav top to bottom reads like the brief: the data layer, the decisions it
// feeds, running it in production, and the plan.

import {
  Activity, AlertTriangle, Bot, Database, FileCheck2, GitBranch, Milestone, Radio, RotateCcw,
  Scale, ShieldCheck, TrendingUp,
} from "lucide-react";

const PAGE_MODULES = import.meta.glob("./pages/*/*.jsx", { eager: true });

export const MODULE_META = {
  Desk:       { label: "Desk view",            icon: Radio,         group: "Data",       order: 0, slug: "desk" },
  Feeds:      { label: "Feeds & contracts",    icon: FileCheck2,    group: "Data",       order: 1 },
  Pipeline:   { label: "Pipeline & lineage",   icon: GitBranch,     group: "Data",       order: 2 },
  Quality:    { label: "Checks & quarantine",  icon: ShieldCheck,   group: "Data",       order: 3 },
  Recovery:   { label: "Replay & recovery",    icon: RotateCcw,     group: "Data",       order: 4 },
  Query:      { label: "Query layer",          icon: Database,      group: "Data",       order: 5 },
  Decisions:  { label: "Decisions & models",   icon: TrendingUp,    group: "Decisions",  order: 6 },
  Tradeoffs:  { label: "What controls are worth", icon: Scale,      group: "Decisions",  order: 7 },
  Incidents:  { label: "Incidents",            icon: AlertTriangle, group: "Production", order: 8 },
  Triage:     { label: "AI triage",            icon: Bot,           group: "Production", order: 9 },
  Operations: { label: "Operations",           icon: Activity,      group: "Production", order: 10 },
  Brief:      { label: "First 90 days",        icon: Milestone,     group: "Plan",       order: 11 },
};

function slugify(value) {
  return value.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export function getRoutes() {
  const seen = new Map();
  for (const [path, module] of Object.entries(PAGE_MODULES)) {
    const match = path.match(/^\.\/pages\/([^/]+)\/([^/]+)\.jsx$/);
    if (!match || seen.has(match[1])) continue;
    const section = match[1];
    const meta = MODULE_META[section] || { label: section, order: 99, group: "Other" };
    seen.set(section, {
      section,
      label: meta.label,
      icon: meta.icon || null,
      group: meta.group,
      order: meta.order ?? 99,
      to: `/${meta.slug || slugify(section)}`,
      component: module.default,
    });
  }
  return [...seen.values()].sort((a, b) => a.order - b.order);
}

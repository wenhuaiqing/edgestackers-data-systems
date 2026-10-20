// Render every page in a real browser and fail on anything a person would see:
// console errors, failed API calls, "NaN" or "undefined" on screen, leftovers
// from the template this was forked from, and pages wider than a phone.
//
// Drives the installed Edge rather than Playwright's bundled Chromium.
//
//   BASE=http://localhost:5241 node evals/check-pages.mjs
//   BASE=https://<live url> OUT=./page-shots-live node evals/check-pages.mjs

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE || "http://localhost:5241";
const OUT = process.env.OUT || "./page-shots";
const CHANNEL = process.env.BROWSER_CHANNEL || "msedge";
mkdirSync(OUT, { recursive: true });

const PAGES = ["desk", "feeds", "pipeline", "quality", "recovery", "query", "decisions", "tradeoffs",
  "incidents", "triage", "operations", "brief"];

const FORBIDDEN = ["NaN", "undefined", "[object Object]", "Infinity", "$-", "Invalid Date"];
const FORBIDDEN_PATTERNS = [
  [/Adpen|Reapit|Bathhouse|Soak|lead gen|property group/i, "template leftover"],
  [/—|–|[“”‘’]/, "typographic dash or curly quote (house style is straight quotes and hyphens)"],
];

const browser = await chromium.launch({ channel: CHANNEL });
let failures = 0;

for (const [label, viewport] of [["desktop", { width: 1500, height: 1000 }], ["phone", { width: 390, height: 844 }]]) {
  const ctx = await browser.newContext({ viewport });
  for (const name of PAGES) {
    const page = await ctx.newPage();
    const problems = [];
    page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text().slice(0, 200)}`); });
    page.on("pageerror", (e) => problems.push(`page error: ${e.message.slice(0, 200)}`));
    page.on("response", (r) => {
      if (r.url().includes("/api/") && r.status() >= 500) problems.push(`API ${r.status()}: ${r.url()}`);
    });
    await page.goto(`${BASE}/${name}`, { waitUntil: "networkidle", timeout: 60_000 });
    await page.waitForTimeout(600);
    const text = await page.locator("body").innerText();
    for (const f of FORBIDDEN) if (text.includes(f)) problems.push(`shows "${f}"`);
    for (const [re, why] of FORBIDDEN_PATTERNS) {
      const m = text.match(re);
      if (m) problems.push(`${why}: "${m[0]}"`);
    }
    if (/Loading/.test(text) && text.length < 400) problems.push("still loading");
    if (label === "phone") {
      const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (wide > 2) problems.push(`page is ${wide}px wider than the phone`);
    }
    await page.screenshot({ path: `${OUT}/${label}-${name}.png`, fullPage: label === "desktop" });
    if (problems.length) {
      failures += problems.length;
      console.log(`FAIL ${label} /${name}`);
      for (const p of problems) console.log(`     ${p}`);
    } else {
      console.log(`ok   ${label} /${name}`);
    }
    await page.close();
  }
  await ctx.close();
}
await browser.close();
if (failures) {
  console.log(`\n${failures} problem(s)`);
  process.exit(1);
}
console.log("\nevery page clean");

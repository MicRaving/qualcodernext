/**
 * TEMPORARY probe (deleted after use): real-browser check of the HtmlCoder
 * live coding highlights — do <mark class="qc-live-coding"> elements appear
 * inside the sandboxed srcdoc iframe?
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const API = "http://localhost:8765/api/v1";
const APP = "http://localhost:5173";
const PROJ_DIR = path.join(os.tmpdir(), "qc-probe");
const PROJ_PATH = path.join(PROJ_DIR, "Probe.qda");

const HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Probe page</title>
<style>body { font-family: sans-serif; } .hot { color: #c00; }</style>
<script>document.body.dataset.evil = "ran";</script>
</head>
<body>
  <h1>Weather report</h1>
  <p>The temperature rose <strong>above 30&deg;C</strong> today.</p>
  <p>Rain is expected tomorrow in the <em>north</em>.</p>
  <ul>
    <li>Sunny intervals</li>
    <li>Wind: light</li>
  </ul>
</body>
</html>
`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function apiJson(url, opts) {
  const res = await fetch(url, opts);
  const body = await res.text();
  if (!res.ok) throw new Error(`HTTP ${res.status} on ${url}: ${body}`);
  return body ? JSON.parse(body) : null;
}

fs.rmSync(PROJ_DIR, { recursive: true, force: true });
fs.mkdirSync(PROJ_DIR, { recursive: true });

// 1. project
console.log("== creating project ==");
await apiJson(`${API}/projects`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ project_path: PROJ_PATH }),
});

// 2. import the html source
console.log("== importing html ==");
const form = new FormData();
form.append("file", new Blob([HTML], { type: "text/html" }), "page.html");
const source = await apiJson(`${API}/sources/import`, { method: "POST", body: form });
console.log("source id:", source.id, "name:", source.name, "media_type:", source.media_type);
console.log("fulltext:", JSON.stringify(source.fulltext));

// 3. code + codings
console.log("== creating code + codings ==");
const code = await apiJson(`${API}/codes`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ name: "Weather" }),
});
console.log("code cid:", code.cid);

const full = source.fulltext;
const spans = [
  { sel: "temperature rose", pos0: full.indexOf("temperature rose") },
  { sel: "Rain is expected", pos0: full.indexOf("Rain is expected") },
  { sel: "Sunny intervals", pos0: full.indexOf("Sunny intervals") },
];
for (const s of spans) {
  if (s.pos0 < 0) throw new Error(`span "${s.sel}" not found in fulltext`);
  const row = await apiJson(`${API}/codings/text`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ cid: code.cid, fid: source.id, seltext: s.sel, pos0: s.pos0, pos1: s.pos0 + s.sel.length }),
  });
  console.log("coding:", row.ctid, JSON.stringify(row.seltext));
}

// 4. real browser
console.log("== launching chromium ==");
const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") console.log("[parent console]", m.type(), m.text());
});
page.on("pageerror", (e) => console.log("[parent pageerror]", e.message));

// Probe installed in EVERY frame (incl. the srcdoc iframe) before any script runs.
await page.addInitScript(() => {
  window.__qcProbe = { messages: [], errors: [] };
  window.addEventListener("error", (e) => window.__qcProbe.errors.push(String(e.message)));
  window.addEventListener("unhandledrejection", (e) => window.__qcProbe.errors.push("rejection " + e.reason));
  window.addEventListener("message", (e) => {
    window.__qcProbe.messages.push({
      type: e.data?.type,
      n: Array.isArray(e.data?.codings) ? e.data.codings.length : -1,
      origin: e.origin,
      isParent: e.source === window.parent,
      time: Date.now(),
    });
  });
});

await page.goto(APP + "/");

// Open the project from the recent list (created via API above).
const recent = page.getByRole("button", { name: PROJ_PATH, exact: true });
await recent.waitFor({ timeout: 20_000 });
await recent.click();
await page.getByRole("button", { name: "Coding", exact: true }).waitFor({ timeout: 30_000 });
await page.getByRole("button", { name: "Coding", exact: true }).click();

const row = page.getByRole("row").filter({ hasText: "page.html" });
await row.waitFor({ timeout: 20_000 });
await row.click();

// HtmlCoder: webpage pane is visible by default.
await page.locator("iframe").first().waitFor({ timeout: 20_000 });
await page.waitForTimeout(4000);

const frame = page.frames().find((f) => f.url().startsWith("about:srcdoc")) ?? page.frames().find((f) => f !== page.mainFrame());

const probe = await frame.evaluate(() => ({
  markCount: document.querySelectorAll("mark.qc-live-coding").length,
  marks: Array.from(document.querySelectorAll("mark.qc-live-coding")).slice(0, 10).map((m) => ({ text: m.textContent, cls: m.className })),
  origin: window.origin,
  frameUrl: window.location.href,
  qcProbe: window.__qcProbe,
  bodyText: document.body ? document.body.innerText.slice(0, 300) : null,
  evilRan: document.body ? document.body.dataset.evil : null,
  srcdocHasScript: null,
}));

const srcdocInfo = await page.locator("iframe").first().evaluate((f) => ({
  hasInjectedScript: (f.getAttribute("srcdoc") ?? "").includes("qc-live-coding"),
  srcdocLen: (f.getAttribute("srcdoc") ?? "").length,
}));

console.log("\n===== PROBE RESULT (before fix) =====");
console.log("frame origin:", probe.origin);
console.log("mark count in iframe:", probe.markCount);
console.log("marks:", JSON.stringify(probe.marks));
console.log("srcdoc contains injected script:", srcdocInfo.hasInjectedScript, "(len", srcdocInfo.srcdocLen + ")");
console.log("body innerText:", JSON.stringify(probe.bodyText));
console.log("page's own script ran (evilRan):", probe.evilRan);
console.log("frame messages:", JSON.stringify(probe.qcProbe.messages, null, 1));
console.log("frame errors:", JSON.stringify(probe.qcProbe.errors));

// Force one more postMessage cycle to be sure timing isn't the issue.
await page.evaluate((sid) => {
  window.dispatchEvent(new CustomEvent("qc:codings-changed"));
}, source.id);
await page.waitForTimeout(2000);
const probe2 = await frame.evaluate(() => ({
  markCount: document.querySelectorAll("mark.qc-live-coding").length,
  messages: window.__qcProbe.messages,
}));
console.log("\nafter forced refresh — mark count:", probe2.markCount);

await browser.close();
console.log("== done ==");

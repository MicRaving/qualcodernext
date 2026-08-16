/**
 * Screenshot capture for the QCnext documentation.
 *
 * Drives the REAL app (backend :8765 + vite :5173) with the seeded demo
 * project, and captures a screenshot of every screen/dialog into
 * docs/screenshots/.
 *
 * Run from frontend/ :  node ../temp/.../shots.mjs   (uses the app's node_modules)
 */
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const OUT = "D:\\Downloads\\qualcoder-rework\\docs\\screenshots";
const PROJECT = "C:\\Users\\marvi\\AppData\\Local\\Temp\\opencode\\qc-docs\\demo\\Qualitative Study.qda";
const BASE = "http://localhost:5173";
const BACKEND = "http://127.0.0.1:8765/api/v1";

fs.mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch({
  headless: true,
  viewport: { width: 1520, height: 950 },
  deviceScaleFactor: 1,
});
const page = await browser.newPage({ viewport: { width: 1520, height: 950 } });
page.setDefaultTimeout(30_000);

// --- animation kill-switch (same as the e2e helpers)
await page.addInitScript(() => {
  const style = document.createElement("style");
  style.textContent =
    "*{animation:none!important;transition:none!important;scroll-behavior:auto!important}";
  document.head.appendChild(style);
});

const shot = async (name) => {
  // settle two frames so any height-adapted layout is stable
  await page.evaluate(() => new Promise(requestAnimationFrame));
  await sleep(120);
  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
  console.log("shot", name);
};

// open the app and wait for the boot gate
await page.goto(BASE);
await page.waitForSelector("text=QCnext", { timeout: 60_000 });
await sleep(1500);

// --- no-project dashboard (app start state)
await shot("01-dashboard-no-project.png");

// open the demo project from the recent list (fallback: the Open dialog)
const recent = page.getByRole("button", { name: PROJECT, exact: true });
if ((await recent.count()) > 0) {
  await recent.first().click();
} else {
  await page.getByRole("button", { name: "Open project", exact: true }).click();
  await page.locator("#open-path").fill(PROJECT);
  await page.getByRole("button", { name: "Open", exact: true }).click();
}
// wait for the project shell: the file-groups sidebar appears and the
// "Coding" (Files) nav button becomes enabled
await page.waitForSelector("text=Text documents", { timeout: 60_000 });
await page.waitForFunction(() => {
  const b = Array.from(document.querySelectorAll("button")).find(
    (x) => (x.getAttribute("aria-label") === "Coding" || x.title === "Coding") && x.textContent?.includes("Coding"),
  );
  return b && !b.disabled;
}, { timeout: 60_000 });
await sleep(1200);

// dashboard with project open
await shot("02-dashboard-project.png");

// ---------------------------------------------------------------- Files
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(800);
await shot("03-files.png");

// ---------------------------------------------------------------- Text coder
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
await page.getByRole("row").filter({ hasText: "interview-1.txt" }).click();
await page.waitForTimeout(1500);
await shot("04-coder-text.png");

// ---------------------------------------------------------------- PDF coder
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
await page.getByRole("row").filter({ hasText: "evaluation-report.pdf" }).click();
await page.waitForTimeout(2500);
await shot("05-coder-pdf.png");

// ---------------------------------------------------------------- Image coder
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
await page.getByRole("row").filter({ hasText: "village-photo.png" }).click();
await page.waitForTimeout(1500);
await shot("06-coder-image.png");

// ---------------------------------------------------------------- CSV coder
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
await page.getByRole("row").filter({ hasText: "survey-comments.csv" }).click();
await page.waitForTimeout(1500);
await shot("07-coder-csv.png");

// ---------------------------------------------------------------- AV coder
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
await page.getByRole("row").filter({ hasText: "recording.wav" }).click();
await page.waitForTimeout(2000);
await shot("08-coder-av.png");

// ---------------------------------------------------------------- Cases
await page.getByRole("button", { name: "Cases", exact: true }).click();
await page.waitForTimeout(1000);
await shot("09-cases.png");

// ---------------------------------------------------------------- Notes (journal)
await page.getByRole("button", { name: "Journal", exact: true }).click();
await page.waitForTimeout(800);
await shot("10-notes-journal.png");

// ---------------------------------------------------------------- QTT
await page.getByRole("button", { name: "Crafter", exact: true }).click();
await page.waitForTimeout(800);
await shot("11-qtt.png");

// ---------------------------------------------------------------- Reports
await page.getByRole("button", { name: "Reports", exact: true }).click();
await page.waitForTimeout(800);
await shot("12-reports-code-frequencies.png");

// code segments
await page.getByRole("button", { name: /Code segments/ }).click();
await page.waitForTimeout(1000);
await shot("13-reports-code-segments.png");

// file x code
await page.getByRole("button", { name: /File \u00d7 code/ }).click();
await page.waitForTimeout(1000);
await shot("14-reports-file-code.png");

// code relations
await page.getByRole("button", { name: /Code relations/ }).click();
await page.waitForTimeout(1000);
await shot("15-reports-code-relations.png");

// interrater
await page.getByRole("button", { name: /Interrater reliability/ }).click();
await page.waitForTimeout(1000);
await shot("16-reports-interrater.png");

// text & corpus
await page.getByRole("button", { name: /Text & corpus/ }).click();
await page.waitForTimeout(1000);
await shot("17-reports-text-corpus.png");

// dictionary
await page.getByRole("button", { name: /Dictionary/ }).click();
await page.waitForTimeout(1000);
await shot("18-reports-dictionary.png");

// stats
await page.getByRole("button", { name: /Statistics/ }).click();
await page.waitForTimeout(1000);
await shot("19-reports-stats.png");

// summary table
await page.getByRole("button", { name: /Summary table/ }).click();
await page.waitForTimeout(1000);
await shot("20-reports-summary-table.png");

// sentiment
await page.getByRole("button", { name: /Sentiment analysis/ }).click();
await page.waitForTimeout(1000);
await shot("21-reports-sentiment.png");

// document compare
await page.getByRole("button", { name: /Document comparison/ }).click();
await page.waitForTimeout(1000);
await shot("22-reports-doc-compare.png");

// codebook (tool)
await page.getByRole("button", { name: /Codebook/ }).click();
await page.waitForTimeout(1000);
await shot("23-reports-codebook.png");

// references (tool)
await page.getByRole("button", { name: /References/ }).click();
await page.waitForTimeout(1000);
await shot("24-reports-references.png");

// SQL (tool)
await page.getByRole("button", { name: /SQL report/ }).click();
await page.waitForTimeout(1000);
await shot("25-reports-sql.png");

// R console
await page.getByRole("button", { name: /R console/ }).click();
await page.waitForTimeout(1000);
await shot("26-reports-r-console.png");

// ---------------------------------------------------------------- Graphs
await page.getByRole("button", { name: /Graphs/ }).click();
await page.waitForTimeout(1500);
await shot("27-graphs.png");

// ---------------------------------------------------------------- History
await page.getByRole("button", { name: "History", exact: true }).click();
await page.waitForTimeout(1000);
await shot("28-history.png");

// ---------------------------------------------------------------- AI pane
await page.getByRole("button", { name: "AI", exact: true }).click();
await page.waitForTimeout(1000);
await shot("29-ai.png");

// ---------------------------------------------------------------- Creative pane
await page.getByRole("button", { name: "Creative", exact: true }).click();
await page.waitForTimeout(1000);
await shot("30-creative.png");

// ---------------------------------------------------------------- Settings
await page.getByRole("button", { name: "Settings", exact: true }).click();
await page.waitForTimeout(1000);
await shot("31-settings.png");

// ---------------------------------------------------------------- Inspector (code details)
await page.getByRole("button", { name: "Creative", exact: true }).click(); // close creative
await page.getByRole("button", { name: "Coding", exact: true }).click();
await page.waitForTimeout(400);
// click a code in the sidebar to show its details in the Inspector
await page.getByRole("button", { name: "Code", exact: true }).first().click();
await page.waitForTimeout(800);
await shot("32-inspector-code.png");

await browser.close();
console.log("ALL SHOTS DONE ->", OUT);

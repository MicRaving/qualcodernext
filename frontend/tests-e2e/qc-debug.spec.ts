/**
 * TEMPORARY DEBUG SPEC — right-click inside the frame.
 */
import { expect, test, type Page } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-tabtest");
const PROJECT_PATH = path.join(E2E_ROOT, "HtmlCodingProbe.qda");
const HTML_PATH = path.join(E2E_ROOT, "probe_page.html");

test.describe.configure({ mode: "serial" });

test.beforeAll(() => {
  fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(
    HTML_PATH,
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Probe</title></head><body>" +
      "<h1>Probe page</h1>" +
      "<p>The quick brown fox jumps over the lazy dog.</p>" +
      "<p>Another line of research text to select.</p>" +
      "</body></html>",
    "utf-8",
  );
});

async function createProject(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
}

test("debug right-click", async ({ page }) => {
  await page.addInitScript(() => {
    const seen: unknown[] = [];
    window.addEventListener("message", (e) => {
      if (e.data && typeof e.data === "object" && "type" in e.data && String(e.data.type).startsWith("qc:")) {
        seen.push(e.data);
      }
    });
    (window as unknown as { __qcSeen: unknown[] }).__qcSeen = seen;
  });

  await createProject(page);
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [HTML_PATH]);
  await expect(page.getByRole("row").filter({ hasText: "probe_page.html" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("row").filter({ hasText: "probe_page.html" }).click();

  const fl = page.frameLocator('iframe[title="Webpage"]');
  await expect(fl.locator("h1").first()).toBeVisible({ timeout: 30_000 });
  const frame = page.frames().find((f) => f.url() === "about:srcdoc");
  expect(frame).toBeTruthy();

  // Code a selection first (same flow as the probe).
  const p = fl.locator("p").first();
  const box = await p.boundingBox();
  const y = box!.y + box!.height / 2;
  await page.mouse.move(box!.x + box!.width * 0.12, y);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.55, y, { steps: 8 });
  await page.mouse.up();
  const toolbar = page.getByRole("toolbar", { name: "Webpage selection actions" });
  await expect(toolbar).toBeVisible({ timeout: 10_000 });
  await toolbar.getByRole("button", { name: /Pick a code/ }).click();
  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("WebMarked");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });
  await expect(fl.locator("mark.qc-live-coding").first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(300);

  const mark = fl.locator("mark.qc-live-coding").first();
  const mb = await mark.boundingBox();
  console.log("mark box:", mb);

  // Inspect the frame at the right-click point BEFORE clicking.
  const probe = await frame!.evaluate(() => {
    const el = document.elementFromPoint(200, 100);
    const r = document.caretRangeFromPoint(200, 100);
    return {
      el: el ? `${el.tagName}.${el.className} text="${(el.textContent || "").slice(0, 20)}"` : null,
      caret: r
        ? `${r.startContainer.nodeName}[${r.startContainer.nodeValue ? r.startContainer.nodeValue.slice(0, 12) : ""}]@${r.startOffset}`
        : null,
    };
  });
  console.log("at (200,100):", JSON.stringify(probe));

  // A console hook to catch errors in the frame.
  frame!.on("console", (msg) => console.log("frame console:", msg.type(), msg.text()));
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("page console error:", msg.text());
  });
  page.on("pageerror", (err) => console.log("page error:", err.message));

  // Right-click at the mark center.
  await page.mouse.click(mb!.x + mb!.width / 2, mb!.y + mb!.height / 2, { button: "right" });
  await page.waitForTimeout(600);

  const seen = await page.evaluate(() => (window as unknown as { __qcSeen: unknown[] }).__qcSeen);
  console.log("seen:", JSON.stringify(seen));
});

/**
 * Coding-flow regression suite: graph create/delete, PDF text marking
 * (shared codings with the plain-text mode), and the multi-code autocode
 * dialog. All tests share ONE project per run (created by the first test,
 * re-opened from the recent-projects list by the later ones) — the backend
 * process persists across tests, so creating a fresh project per test would
 * only cost time without isolating anything.
 */
import { expect, test, type Page } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execSync } from "node:child_process";

test.describe.configure({ mode: "serial" });

const E2E_ROOT = path.join(os.tmpdir(), "qc-tabtest");
const PROJECT_PATH = path.join(E2E_ROOT, "CodingFlows.qda");

test.beforeAll(() => {
  fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
});

/**
 * The backend's migration chain rewrites the project row's `about` field on
 * EVERY open, and `open_project` rejects a database whose `about` lacks
 * "QualCoder" — so a project can only be opened once per backend session.
 * Restore the marker directly (same quirk as features.spec.ts).
 */
const BACKEND_PYTHON = (() => {
  const venvPython = path.resolve(
    process.cwd(),
    "..",
    "backend",
    ".venv",
    "Scripts",
    "python.exe",
  );
  return fs.existsSync(venvPython) ? venvPython : "python";
})();

async function repairProjectMeta(): Promise<void> {
  try {
    const { DatabaseSync } = await import("node:sqlite");
    const db = new DatabaseSync(path.join(PROJECT_PATH, "data.qda"));
    try {
      db.exec("UPDATE project SET about='QualCoder 4.0' WHERE about NOT LIKE 'QualCoder%'");
    } finally {
      db.close();
    }
  } catch {
    /* the open below will surface any real problem */
  }
}

/**
 * Make sure the shared project is open. Fresh pages land on the welcome
 * screen, so re-open from the recent-projects list; clear the backend's
 * stale lock file and repair the `about` marker first.
 */
async function ensureProjectOpen(page: Page) {
  const closeBtn = page.getByRole("button", { name: "Cases" });
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/");
    fs.rmSync(path.join(PROJECT_PATH, "project_in_use.lock"), { force: true });
    await repairProjectMeta();
    const recent = page.getByRole("button", { name: PROJECT_PATH, exact: true });
    try {
      await expect(recent).toBeVisible({ timeout: 5_000 });
      await recent.click();
      await expect(closeBtn).toBeEnabled({ timeout: 30_000 });
      return;
    } catch {
      /* reload and retry once more */
    }
  }
  throw new Error(`Could not open ${PROJECT_PATH} after 3 attempts`);
}

/** Create the shared project (first test only). */
async function createProject(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
}

/* ------------------------------------------------------------------ graphs */

test("graph create updates list, delete works", async ({ page }) => {
  await createProject(page);

  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await page.getByRole("button", { name: "Graphs", exact: true }).click();
  await expect(page.getByLabel("Select graph…")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Add", exact: true }).click();
  const nameDialog = page.getByRole("dialog", { name: /New graph/ });
  await expect(nameDialog).toBeVisible();
  await nameDialog.locator("input").first().fill("Map A");
  await nameDialog.getByRole("button", { name: "New graph" }).click();
  await expect(nameDialog).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(1);
  await expect(page.getByLabel("Select graph…").locator("option").first()).toHaveText("Map A");

  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(nameDialog).toBeVisible();
  await nameDialog.locator("input").first().fill("Map B");
  await nameDialog.getByRole("button", { name: "New graph" }).click();
  await expect(nameDialog).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(2);

  await page.getByRole("button", { name: "Delete the open graph" }).click();
  const confirm = page.getByRole("dialog", { name: /Delete/ });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "Delete" }).click();
  await expect(confirm).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(1);
  await expect(page.locator("[class*=banner]")).toHaveCount(0);
});

/* ----------------------------------------------------------------- pdf text */

test("pdf text marking codes into the plain-text layer", async ({ page }) => {
  await ensureProjectOpen(page);
  const pdfPath = path.join(E2E_ROOT, `pdf_${Date.now() % 100000}.pdf`);
  const script = `
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "The quick brown fox jumps over the lazy dog.")
page.insert_text((72, 130), "Another line of important research text here.")
doc.save(r"${pdfPath}")
`;
  const scriptPath = path.join(E2E_ROOT, `make_pdf_${Date.now() % 100000}.py`);
  fs.writeFileSync(scriptPath, script, "utf-8");
  execSync(`"${BACKEND_PYTHON}" "${scriptPath}"`);

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [pdfPath]);
  await expect(page.getByRole("row").filter({ hasText: "pdf_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "pdf_" }).click();

  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });

  // pdf.js sizes the canvas once it reports the page geometry — wait for a
  // rendered box instead of a fixed sleep.
  const canvas = page.locator("canvas").first();
  await expect
    .poll(async () => (await canvas.boundingBox())?.width ?? 0, { timeout: 20_000 })
    .toBeGreaterThan(100);
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.16, box!.y + box!.height * 0.112);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.85, box!.y + box!.height * 0.135, { steps: 8 });
  await page.mouse.up();

  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("PdfMarked");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });
  await expect(page.locator("[class*=banner]")).toHaveCount(0);

  // Plain-text pane on: the extracted text (with the marked segment) shows
  // next to the rendered PDF. "Plain text" is a toggle — pressing it again
  // returns to the rendered PDF only.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.getByText("The quick brown fox jumps over the lazy dog.")).toBeVisible({
    timeout: 20_000,
  });
  // The marked segment lives in the plain-text pane (the PDF pane's
  // overlays also carry the .qc-seg class but are empty) — scope by text.
  const seg = page.locator(".qc-seg", { hasText: "The quick brown fox jumps over the lazy dog." }).first();
  await expect(seg).toBeVisible({ timeout: 15_000 });
  await expect(seg).toContainText("The quick brown fox jumps over the lazy dog.");

  // Switch back to the rendered PDF — canvases re-render and text marking works.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 20_000 });
  const canvas2 = page.locator("canvas").first();
  await expect
    .poll(async () => (await canvas2.boundingBox())?.width ?? 0, { timeout: 20_000 })
    .toBeGreaterThan(100);
  const box2 = await canvas2.boundingBox();
  expect(box2).not.toBeNull();
  await page.mouse.move(box2!.x + box2!.width * 0.16, box2!.y + box2!.height * 0.19);
  await page.mouse.down();
  await page.mouse.move(box2!.x + box2!.width * 0.85, box2!.y + box2!.height * 0.21, { steps: 6 });
  await page.mouse.up();
  const picker2 = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker2).toBeVisible({ timeout: 10_000 });
  await picker2.getByRole("button", { name: "Close" }).click();
  await expect(picker2).toBeHidden();
  await expect(page.locator("[class*=banner]")).toHaveCount(0);
});

/* ----------------------------------------------------------------- csv table */

test("csv table view codes cell text and shows the badge", async ({ page }) => {
  await ensureProjectOpen(page);
  const csvPath = path.join(E2E_ROOT, `csv_${Date.now() % 100000}.csv`);
  fs.writeFileSync(
    csvPath,
    "author,likes,date,comment\n" +
      "alice,12,2026-01-01,This is a great comment about research\n" +
      "bob,3,2026-01-02,Another comment with interesting words\n",
    "utf-8",
  );

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [csvPath]);
  await expect(page.getByRole("row").filter({ hasText: "csv_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "csv_" }).click();

  // The table view opens (4 columns x 2 rows) with a sticky header.
  await expect(page.getByRole("button", { name: "Table" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("4 columns · 2 rows")).toBeVisible();

  // Create a code via the sidebar, then select part of the comment cell.
  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByTestId("inline-name-edit")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("inline-name-edit").fill("TblCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("TblCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
  // Clicking the code makes it the ACTIVE code (no selection exists yet,
  // so the assign event is a no-op).
  await page.getByRole("button", { name: "TblCode", exact: true }).first().click();

  const cell = page.locator('[data-qc-cell-text]').filter({ hasText: "This is a great" }).first();
  await expect(cell).toBeVisible();
  const box = await cell.boundingBox();
  expect(box).not.toBeNull();
  // Integer coordinates: Chromium's drag-selection is unreliable when the
  // pointer lands on a fractional pixel (a half-pixel start collapses the
  // selection instead of anchoring it).
  const sx = Math.round(box!.x + box!.width * 0.05);
  const ex = Math.round(box!.x + box!.width * 0.6);
  const sy = Math.round(box!.y + box!.height / 2);
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(ex, sy, { steps: 6 });
  await page.mouse.up();

  // The toolbar's Code button always opens the code flyout — pick TblCode
  // there and the coding lands in the cell.
  const toolbar = page.getByRole("toolbar", { name: "Text selection actions" });
  await expect(toolbar).toBeVisible({ timeout: 10_000 });
  await toolbar.getByRole("button", { name: /^Code…$/ }).click();
  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByText("TblCode", { exact: true }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });
  await expect(toolbar).toBeHidden({ timeout: 10_000 });

  // The cell now shows ONLY the marked sub-span highlighted (not the whole
  // cell) plus a code badge; the details bar lists the coding.
  const marked = page
    .locator('[data-qc-cell-text] span[style*="background-color"]')
    .filter({ hasText: "is a great" })
    .first();
  await expect(marked).toBeVisible({ timeout: 10_000 });
  const markedText = (await marked.textContent()) ?? "";
  expect(markedText.length).toBeGreaterThan(0);
  expect(markedText.length).toBeLessThan("This is a great comment about research".length);
  const badge = page.locator("[data-qc-badge]").first();
  await expect(badge).toBeVisible();
  await expect(badge).toContainText("TblCode");
  await expect(page.getByText("Coding details", { exact: true })).toBeVisible();
  // Nothing was removed yet — Unmark last stays disabled.
  await expect(page.getByRole("button", { name: /Unmark last/ })).toBeDisabled();

  // Switch to plain text and back: no selection/toolbar leaks over.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.getByText("This is a great comment about research")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByRole("toolbar", { name: "Text selection actions" })).toHaveCount(0);
  await page.getByRole("button", { name: "Table" }).click();
  await expect(page.locator("[data-qc-badge]").first()).toBeVisible({ timeout: 10_000 });

  // Remove the coding from the details bar, then Unmark restores it.
  // (The details bar opens when a coded cell/badge is clicked.)
  await page.locator("[data-qc-badge]").first().click();
  await expect(page.getByRole("button", { name: "Remove coding for TblCode" })).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Remove coding for TblCode" }).click();
  await expect(page.locator("[data-qc-badge]")).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByRole("button", { name: /Unmark last/ })).toBeEnabled();
  await page.getByRole("button", { name: /Unmark last/ }).click();
  await expect(page.locator("[data-qc-badge]").first()).toContainText("TblCode", {
    timeout: 10_000,
  });
});

/* ---------------------------------------------------------------- autocode */

test("autocode dialog codes multiple selected codes", async ({ page }) => {
  await ensureProjectOpen(page);
  const txtPath = path.join(E2E_ROOT, `ac_${Date.now() % 100000}.txt`);
  fs.writeFileSync(txtPath, "cat dog cat bird\nsecond line here\n", "utf-8");

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [txtPath]);
  await expect(page.getByRole("row").filter({ hasText: "ac_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "ac_" }).click();
  await expect(page.getByRole("button", { name: "Code", exact: true })).toBeVisible({
    timeout: 20_000,
  });

  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByTestId("inline-name-edit")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("inline-name-edit").fill("CatCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("CatCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByTestId("inline-name-edit")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("inline-name-edit").fill("BirdCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("BirdCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "Autocode" }).click();
  const ad = page.getByRole("dialog", { name: "Autocode" });
  await expect(ad).toBeVisible();
  await ad.getByLabel("Coding prompt").fill('"cat" "bird"');
  await ad.getByText("CatCode").click();
  await ad.getByText("BirdCode").click();
  await expect(ad.getByText("2 codes selected")).toBeVisible();
  await expect(ad.getByText("Suggest new codes")).toBeVisible();
  // The dialog also has a "Autocode with dictionary" button — match the main
  // action exactly so the two never collide.
  await ad.getByRole("button", { name: "Autocode", exact: true }).click();

  // Result: 3 matched spans x 2 codes = 6 codings (the dialog then closes).
  await expect(ad.getByText(/Autocoded \d+ instances/)).toBeVisible({ timeout: 15_000 });
  await expect(ad).toBeHidden({ timeout: 10_000 });
});

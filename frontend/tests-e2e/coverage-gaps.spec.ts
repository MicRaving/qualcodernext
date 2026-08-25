/**
 * E2E coverage for the most valuable previously-untested user operations
 * (see tests-e2e/COVERAGE.md for the full matrix):
 *  - segment link copy/paste across files + jump via the link marker
 *  - text-coder bookmark set/go/persist
 *  - dictionary autocode end-to-end (report page: create dict, add entry,
 *    autocode all sources, verify the coded span in the coder)
 *  - send-to-QTT from the text coder selection toolbar
 *  - the Analyze "Publish" dialog with a real Word (.docx) export
 *
 * All tests share ONE project per run (created by the first test, re-opened
 * from the recent-projects list by the later ones).
 */
import { expect, test, type Page } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-gaps");
const PROJECT_PATH = path.join(E2E_ROOT, "Gaps.qda");
const TXT_A = path.join(E2E_ROOT, "gaps_a.txt");
const TXT_B = path.join(E2E_ROOT, "gaps_b.txt");
const TXT_DICT = path.join(E2E_ROOT, "gaps_dict.txt");

test.beforeAll(() => {
  fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(TXT_A, "Alpha one two three four.\nBeta line here too.\n", "utf-8");
  fs.writeFileSync(TXT_B, "Gamma one two three.\nDelta line here too.\n", "utf-8");
  fs.writeFileSync(
    TXT_DICT,
    "The client felt happy with the service.\nSecond line without the term.\n",
    "utf-8",
  );
});

test.describe.configure({ mode: "serial" });

/**
 * The backend's migration chain rewrites the project row's `about` field on
 * EVERY open, and `open_project` rejects a database whose `about` lacks
 * "QualCoder" — so a project can only be opened once per backend session.
 * Restore the marker directly (same quirk as features.spec.ts).
 */
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

/** Make sure the shared project is open (create it on the first call). */
async function ensureProjectOpen(page: Page, create = false) {
  const closeBtn = page.getByRole("button", { name: "Cases" });
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/");
    fs.rmSync(path.join(PROJECT_PATH, "project_in_use.lock"), { force: true });
    await repairProjectMeta();
    if (create) {
      await page.getByRole("button", { name: "New project" }).click();
      const dialog = page.getByRole("dialog", { name: "New project" });
      await dialog.locator("#create-path").fill(PROJECT_PATH);
      await dialog.getByRole("button", { name: "Create project" }).click();
      await expect(closeBtn).toBeEnabled({ timeout: 30_000 });
      return;
    }
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

/** Files view → open a text source in the coder and wait for its text. */
async function openTextFile(page: Page, fileName: string, firstLine: string) {
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.getByRole("row").filter({ hasText: fileName }).click();
  await expect(page.getByText(firstLine, { exact: false })).toBeVisible({ timeout: 20_000 });
}

/** Mouse-select the first line of the open document. */
async function selectFirstLine(page: Page, firstLine: string) {
  // getByText resolves to the document container (its text contains the
  // substring); the container's box covers ALL lines, so drag at the FIRST
  // line's vertical middle (text-sm leading-6 = 24px line height) instead of
  // the box center, which would land on the line boundary.
  const line = page.getByText(firstLine, { exact: false }).first();
  const box = await line.boundingBox();
  expect(box).not.toBeNull();
  const y = box!.y + 12;
  await page.mouse.move(box!.x + 4, y);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width - 4, y, { steps: 8 });
  await page.mouse.up();
}

/** Create a code via the sidebar "Code" button + inline name editor. */
async function createCode(page: Page, name: string) {
  await page.getByRole("button", { name: "Code", exact: true }).click();
  const input = page.getByTestId("inline-name-edit");
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill(name);
  await input.press("Enter");
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
}

// ---------------------------------------------------------------------------

test("segment link copy/paste across files and jump via the marker", async ({ page }) => {
  await ensureProjectOpen(page, true);

  // Import the two text fixtures.
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [TXT_A, TXT_B]);
  await expect(page.getByRole("row").filter({ hasText: "gaps_a.txt" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("row").filter({ hasText: "gaps_b.txt" })).toBeVisible();

  // A code is needed later for the marker to render on a coded segment.
  await openTextFile(page, "gaps_a.txt", "Alpha one two three four.");
  await createCode(page, "LinkCode");

  // Copy a segment link from the first line of gaps_a.txt.
  await selectFirstLine(page, "Alpha one two three four.");
  const toolbar = page.getByRole("toolbar", { name: "Text selection actions" });
  await expect(toolbar).toBeVisible({ timeout: 10_000 });
  await toolbar.getByRole("button", { name: "Copy link" }).click();
  await expect(toolbar.getByText("Link copied")).toBeVisible({ timeout: 10_000 });

  // Open gaps_b.txt, select the first line and paste the link onto it.
  await openTextFile(page, "gaps_b.txt", "Gamma one two three.");
  await selectFirstLine(page, "Gamma one two three.");
  await expect(toolbar).toBeVisible({ timeout: 10_000 });
  const paste = toolbar.getByRole("button", { name: "Paste link here" });
  await expect(paste).toBeVisible({ timeout: 10_000 });
  const linked = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().includes("/links"),
    { timeout: 15_000 },
  );
  await paste.click();
  // Pasting re-renders the document when the link lands (refreshLinks) — if
  // the next drag starts before that, the re-render wipes the selection, so
  // wait for the link to be created first.
  await linked;

  // Code the pasted-into span: the link marker renders on the coded segment.
  await selectFirstLine(page, "Gamma one two three.");
  // With no active sidebar code the toolbar's Code button reads "Code…"
  // (i18n "coder.codeAction" — NOT the sidebar's "Code" button).
  await toolbar.getByRole("button", { name: /^Code…$/ }).click();
  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByText("LinkCode", { exact: true }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });

  // The wavy-underline link marker appears next to the coded segment and
  // jumping with it switches to the source file. (The label uses an em-dash:
  // "Linked segment — jump to gaps_a.txt".)
  const marker = page.getByRole("button", { name: /Linked segment.*jump to gaps_a\.txt/ });
  await expect(marker).toBeVisible({ timeout: 10_000 });
  await marker.click();
  await expect(page.getByText("Alpha one two three four.")).toBeVisible({ timeout: 15_000 });
});

// ---------------------------------------------------------------------------

test("bookmark set, go-to and persistence", async ({ page }) => {
  await ensureProjectOpen(page);
  await openTextFile(page, "gaps_b.txt", "Gamma one two three.");

  // The project row seeds a legacy bookmark (bookmarkfile/bookmarkpos), so
  // "Go to bookmark" is enabled from the start; the real state is which file
  // it points at — the Set button fills when the bookmark matches THIS file.
  const setBtn = page.getByRole("button", { name: "Set bookmark" });
  await expect(setBtn).not.toHaveClass(/text-accent/);

  await setBtn.click();
  await expect(setBtn).toHaveClass(/text-accent/, { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Go to bookmark" })).toBeEnabled();

  // The bookmark persists in the backend: reload the app, reopen the file
  // and it still points at gaps_b.txt (button stays filled).
  await page.goto("/");
  await ensureProjectOpen(page);
  await openTextFile(page, "gaps_b.txt", "Gamma one two three.");
  await expect(page.getByRole("button", { name: "Set bookmark" })).toHaveClass(/text-accent/, {
    timeout: 10_000,
  });
  await expect(page.getByRole("button", { name: "Go to bookmark" })).toBeEnabled();
});

// ---------------------------------------------------------------------------

test("dictionary autocode: create dictionary, add entry, code all sources", async ({ page }) => {
  await ensureProjectOpen(page);

  // Import the document that contains the dictionary term.
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [TXT_DICT]);
  await expect(page.getByRole("row").filter({ hasText: "gaps_dict.txt" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "gaps_dict.txt" }).click();
  await expect(page.getByText("The client felt happy with the service.")).toBeVisible({
    timeout: 20_000,
  });
  await createCode(page, "HappyCode");

  // Dictionary report: create a dictionary and one term → code entry.
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Dictionary", exact: true }).click();

  // The "Create dictionary" label matches both the name input and the Add
  // button — target the input via its placeholder.
  await page.getByPlaceholder("e.g. Emotions").fill("Mood");
  await page.getByPlaceholder("e.g. Emotions").press("Enter");
  const pick = page.getByLabel("Dictionary:");
  await expect(pick.locator("option")).toContainText(["Mood (0)"]);

  await page.getByLabel("Term").fill("happy");
  await page.getByLabel("Code name").fill("HappyCode");
  await page.getByRole("button", { name: "Add entry" }).click();
  // The term lands in the entries table (and, once the frequency matrix
  // loads, also as a column header — scope to the entry cell).
  await expect(page.getByRole("cell", { name: "happy", exact: true })).toBeVisible({
    timeout: 15_000,
  });

  // Dictionary autocode over all sources → 1 passage for the term.
  await page.getByRole("button", { name: "Autocode with dictionary" }).click();
  await expect(page.getByText(/Autocoded 1 passages/)).toBeVisible({ timeout: 20_000 });

  // The span is really coded: reopen the document and the segment shows.
  await openTextFile(page, "gaps_dict.txt", "The client felt happy with the service.");
  const seg = page.locator('span[title="HappyCode"]');
  await expect(seg).toBeVisible({ timeout: 15_000 });
  await expect(seg).toContainText("happy");
});

// ---------------------------------------------------------------------------

test("send-to-QTT from the text coder selection toolbar", async ({ page }) => {
  await ensureProjectOpen(page);

  // Create a worksheet to send into.
  await page.getByRole("button", { name: "Crafter", exact: true }).click();
  await expect(page.getByText("No worksheets yet. Add one to collect insights.")).toBeVisible({
    timeout: 10_000,
  });
  await page.getByRole("button", { name: "Add", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "New worksheet" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Worksheet name…").fill("Evidence");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 10_000 });

  // Select a span in the coder and send it to the worksheet.
  await openTextFile(page, "gaps_b.txt", "Gamma one two three.");
  await selectFirstLine(page, "Gamma one two three.");
  const toolbar = page.getByRole("toolbar", { name: "Text selection actions" });
  await expect(toolbar).toBeVisible({ timeout: 10_000 });
  await toolbar.getByRole("button", { name: "Send to Crafter" }).click();
  const menu = page.getByRole("menu", { name: "Send to worksheet" });
  await expect(menu).toBeVisible({ timeout: 10_000 });
  await menu.getByRole("menuitem", { name: "Evidence" }).click();
  // The menu closes as the segment is stored (the toolbar disappears with
  // the cleared selection — the stored item below is the real proof).
  await expect(menu).toBeHidden({ timeout: 10_000 });

  // The worksheet now holds the segment item: the UI renders the quote (the
  // paragraph line-clamps, so match the prefix) and the source chip…
  await page.getByRole("button", { name: "Crafter", exact: true }).click();
  // Kind label disambiguates from the row's hover-visible rename button
  // (role-name matching is substring by default).
  await page.getByRole("button", { name: "Evidence Qualitative" }).click();
  await expect(page.getByRole("button", { name: "gaps_b.txt", exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("Gamma one two three", { exact: false }).first()).toBeVisible();

  // …and the backend stored the exact span (quote text resolved from the
  // source fulltext, anchored on gaps_b.txt).
  const sheets = await page.request.get("http://localhost:8765/api/v1/qtt");
  const qtt = (await sheets.json()) as { id: number; name: string }[];
  const evidence = qtt.find((s) => s.name === "Evidence");
  expect(evidence).toBeTruthy();
  const detail = await page.request.get(
    `http://localhost:8765/api/v1/qtt/${evidence!.id}`,
  );
  const sheet = (await detail.json()) as {
    items: Record<string, { source_text: string; source_name: string }[]>;
  };
  const items = Object.values(sheet.items).flat();
  const seg = items.find((i) => i.source_name === "gaps_b.txt");
  expect(seg).toBeTruthy();
  expect(seg!.source_text).toContain("Gamma one two three");
});

// ---------------------------------------------------------------------------

test("analyze publish dialog exports the current report as Word", async ({ page }) => {
  await ensureProjectOpen(page);

  // Code frequencies needs codings — the earlier tests created LinkCode and
  // HappyCode spans in this shared project.
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Code frequencies/ }).click();
  await expect(page.getByRole("row").filter({ hasText: "LinkCode" })).toBeVisible({
    timeout: 20_000,
  });

  await page.getByRole("button", { name: "Publish", exact: true }).click();
  const pub = page.getByRole("dialog", { name: "Publish report" });
  await expect(pub).toBeVisible({ timeout: 10_000 });

  // Word / Excel / PowerPoint options; file name prefilled from the report.
  const format = pub.getByLabel("Format");
  await expect(format.locator("option")).toContainText([
    "Word (.docx)",
    "Excel (.xlsx)",
    "PowerPoint (.pptx)",
  ]);
  await expect(pub.getByLabel("File name")).toHaveValue(/^code-frequencies-\d{4}-\d{2}-\d{2}$/);

  // Publish as Word: the report downloads as a .docx attachment. (For code
  // frequencies PowerPoint is the pre-selected default — pick Word.)
  await pub.getByLabel("Format").selectOption({ label: "Word (.docx)" });
  const downloadPromise = page.waitForEvent("download", { timeout: 60_000 });
  await pub.getByRole("button", { name: "Publish", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.docx$/i);
});

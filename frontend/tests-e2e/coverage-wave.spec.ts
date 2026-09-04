/**
 * E2E coverage for the second wave of high-value gaps (see
 * tests-e2e/COVERAGE.md for the full matrix):
 *  - History: per-row undo of a coding from the audit log + redo
 *  - Notes: journal entry create/edit/save; code memo via the memos tab
 *  - Files: row context menu — rename (prompt), delete (confirm), and the
 *    Assign-to-case / Replace entries
 *  - Sentiment report: lexicon scoring of coded segments + distribution card
 *  - Statistics report: crosstab with the chi-square card
 *  - Summary table: file×code grid with an inline cell memo edit
 *
 * All tests share ONE project per run (created by the first test, re-opened
 * from the recent-projects list by the later ones). Nothing here needs AI
 * or whisper. The attribute type for the stats test is seeded through the
 * API (no UI for label maps — same approach as roadmap.spec.ts).
 */
import { expect, KILL_ANIMATIONS, test, type Page } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-wave");
const PROJECT_PATH = path.join(E2E_ROOT, "Wave.qda");
const FILE_A = path.join(E2E_ROOT, "file_a.txt");
const FILE_B = path.join(E2E_ROOT, "file_b.txt");
const FILE_CTX = path.join(E2E_ROOT, "files_ctx.txt");

test.beforeAll(() => {
  fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(FILE_A, "Alpha weather bright sunny.\nSecond line calm.\n", "utf-8");
  fs.writeFileSync(FILE_B, "Beta storm dark gloomy.\nFourth line mild.\n", "utf-8");
  fs.writeFileSync(FILE_CTX, "Context menu target file.\nNothing else here.\n", "utf-8");
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

/**
 * Make sure the shared project is open. Fresh pages land on the welcome
 * screen, so re-open from the recent-projects list; clear the backend's
 * stale lock file and repair the `about` marker first. When the recent
 * list has been overwritten (backend pytest runs in this environment keep
 * rewriting ~/.qualcoder/settings.json), fall back to the Open-project
 * dialog — the same user flow with an explicit path.
 */
async function ensureProjectOpen(page: Page) {
  const closeBtn = page.getByRole("button", { name: "Cases", exact: true });
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/");
    fs.rmSync(path.join(PROJECT_PATH, "project_in_use.lock"), { force: true });
    await repairProjectMeta();
    const recent = page.getByRole("button", { name: PROJECT_PATH, exact: true });
    try {
      await expect(recent).toBeVisible({ timeout: 4_000 });
      await recent.click();
    } catch {
      const openDialog = page.getByRole("dialog", { name: "Open project" });
      await page.getByRole("button", { name: "Open project" }).click();
      await expect(openDialog).toBeVisible();
      await openDialog.locator("#open-path").fill(PROJECT_PATH);
      await openDialog.getByRole("button", { name: "Open project" }).click();
    }
    try {
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

/** Files view → open a text source in the coder and wait for its text. */
async function openTextFile(page: Page, fileName: string, firstLine: string) {
  const row = page.getByRole("row").filter({ hasText: fileName });
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await page.getByRole("button", { name: "Coding", exact: true }).click({ timeout: 15_000 });
      await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible({
        timeout: 15_000,
      });
      await expect(row).toBeVisible({ timeout: 20_000 });
      await row.click();
      await expect(page.getByText(firstLine, { exact: false })).toBeVisible({ timeout: 20_000 });
      return;
    } catch {
      if (attempt === 2) throw new Error(`Could not open ${fileName} in the coder`);
      await page.reload();
      await ensureProjectOpen(page);
    }
  }
}

/**
 * Mouse-select one line of the open document. getByText resolves to the
 * document container whose box covers ALL lines (text-sm leading-6 = 24px
 * line height), so line N sits at box.y + N*24; drag at its middle.
 */
async function selectLine(page: Page, firstLine: string, lineIndex = 0) {
  const line = page.getByText(firstLine, { exact: false }).first();
  const box = await line.boundingBox();
  expect(box).not.toBeNull();
  const y = box!.y + lineIndex * 24 + 12;
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

/** Code the current selection with the given code via the sidebar row. */
async function codeSelection(page: Page, codeName: string) {
  await page.getByRole("button", { name: codeName, exact: true }).click();
}

// ---------------------------------------------------------------------------

test("create shared project, import fixtures and code segments", async ({ page }) => {
  await createProject(page);
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [FILE_A, FILE_B]);
  await expect(page.getByRole("row").filter({ hasText: "file_a.txt" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("row").filter({ hasText: "file_b.txt" })).toBeVisible();

  // Codes + two coded segments: WaveCode on file_a L1, WaveCodeB on file_b L1.
  await openTextFile(page, "file_a.txt", "Alpha weather bright sunny.");
  await createCode(page, "WaveCode");
  await createCode(page, "WaveCodeB");
  await selectLine(page, "Alpha weather bright sunny.", 0);
  await codeSelection(page, "WaveCode");
  await expect(page.locator('span[title="WaveCode"]')).toHaveCount(1, { timeout: 10_000 });

  await openTextFile(page, "file_b.txt", "Beta storm dark gloomy.");
  await selectLine(page, "Beta storm dark gloomy.", 0);
  await codeSelection(page, "WaveCodeB");
  await expect(page.locator('span[title="WaveCodeB"]')).toHaveCount(1, { timeout: 10_000 });
});

// ---------------------------------------------------------------------------

test("history undo removes a coding and redo re-applies it", async ({ page }) => {
  await ensureProjectOpen(page);

  // A fresh coding in file_a (line 2 → WaveCodeB) becomes the newest
  // "coding.create" audit row.
  await openTextFile(page, "file_a.txt", "Alpha weather bright sunny.");
  await selectLine(page, "Alpha weather bright sunny.", 1);
  await codeSelection(page, "WaveCodeB");
  await expect(page.locator('span[title="WaveCodeB"]')).toHaveCount(1, { timeout: 10_000 });

  // Open the History pane and narrow to coding creates.
  await page.getByRole("button", { name: "History", exact: true }).click();
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible({ timeout: 10_000 });
  await page.getByLabel("Filter by action").selectOption("coding.create");
  await expect(page.getByText("Coding created", { exact: true }).first()).toBeVisible({
    timeout: 10_000,
  });

  // Undo the newest row — the backend deletes the coding. The open coder
  // keeps its last-fetched codings (HistoryView's refreshProject reloads the
  // sidebar, not the coder), and re-opening the file would close the pane
  // (unmounting it loses the redo stack), so a SECOND page observes the
  // coder while this page keeps the History pane open.
  const undoSent = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().includes("/audit/undo"),
    { timeout: 15_000 },
  );
  await page.getByRole("button", { name: "Undoes this action" }).first().click();
  await undoSent;
  await expect(page.getByText(/deleted code_text #\d+/).first()).toBeVisible({
    timeout: 10_000,
  });

  // Second page: open the shared project and the file — the coding is gone
  // from a fresh fetch, the untouched one survives.
  const observer = await page.context().newPage();
  await observer.addInitScript(KILL_ANIMATIONS);
  await observer.goto("/");
  await ensureProjectOpen(observer);
  await openTextFile(observer, "file_a.txt", "Alpha weather bright sunny.");
  await expect(observer.locator('span[title="WaveCodeB"]')).toHaveCount(0, { timeout: 10_000 });
  await expect(observer.locator('span[title="WaveCode"]')).toHaveCount(1, { timeout: 10_000 });

  // Redo on the first page (the pane never closed) → the coding is back.
  const redoBtn = page.getByRole("button", { name: "Re-apply the last undone change" });
  await expect(redoBtn).toBeEnabled({ timeout: 10_000 });
  const redoSent = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().includes("/audit/redo"),
    { timeout: 15_000 },
  );
  await redoBtn.click();
  await redoSent;
  await expect(page.getByText(/restored code_text #\d+/).first()).toBeVisible({
    timeout: 10_000,
  });

  // The observer re-fetches (switch files, then back) and sees the restored
  // segment.
  await openTextFile(observer, "file_b.txt", "Beta storm dark gloomy.");
  await openTextFile(observer, "file_a.txt", "Alpha weather bright sunny.");
  await expect(observer.locator('span[title="WaveCodeB"]')).toHaveCount(1, { timeout: 10_000 });
  await expect(observer.locator('span[title="WaveCode"]')).toHaveCount(1, { timeout: 10_000 });
  await observer.close();
});

// ---------------------------------------------------------------------------

test("notes: journal entry create/save and a code memo via the memos tab", async ({
  page,
}) => {
  await ensureProjectOpen(page);

  // Journal: nav "Journal" (ribbon) → Add → name + text → Save.
  await page.getByRole("button", { name: "Journal", exact: true }).click();
  await page.getByRole("button", { name: "Add", exact: true }).first().click();
  const nameInput = page.getByLabel("Entry name…");
  await expect(nameInput).toBeVisible({ timeout: 10_000 });
  await nameInput.fill("Wave journal entry");
  await page.getByLabel("Write your journal entry…").fill("Observations from the analysis wave.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Wave journal entry", { exact: true })).toBeVisible({
    timeout: 10_000,
  });

  // Memos tab: open the code inspector, right-click the memo header → the
  // notes view switches to the memos tab with the code-memo tree.
  await openTextFile(page, "file_a.txt", "Alpha weather bright sunny.");
  await page.getByRole("button", { name: "WaveCode", exact: true }).click();
  const memoHeader = page.locator('div[title="Right-click to open the memos view"]');
  await expect(memoHeader).toBeVisible({ timeout: 10_000 });
  await memoHeader.click({ button: "right" });

  // The memo tree lists the codes; select WaveCode and write its memo.
  await expect(page.getByText("Memos", { exact: true }).first()).toBeVisible({
    timeout: 10_000,
  });
  const memoRow = page.getByRole("button", { name: "WaveCode", exact: true });
  await expect(memoRow).toBeVisible({ timeout: 10_000 });
  await memoRow.click();
  const memoArea = page.getByLabel("Write the memo for this code…");
  await expect(memoArea).toBeVisible({ timeout: 10_000 });
  await memoArea.fill("Memo written in the memos workspace");
  const memoPatched = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && /\/codes\/\d+$/.test(new URL(r.url()).pathname),
    { timeout: 15_000 },
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await memoPatched;

  // The tree row now carries the "memo" badge.
  await expect(page.getByRole("button", { name: /^WaveCode memo/ })).toBeVisible({
    timeout: 10_000,
  });

  // Persistence: back in the coder the code inspector shows the memo text.
  await openTextFile(page, "file_a.txt", "Alpha weather bright sunny.");
  await page.getByRole("button", { name: "WaveCode", exact: true }).click();
  await expect(page.getByText("Memo written in the memos workspace")).toBeVisible({
    timeout: 10_000,
  });
});

// ---------------------------------------------------------------------------

test("files row context menu: rename, delete and menu contents", async ({ page }) => {
  await ensureProjectOpen(page);

  // A dedicated throwaway source — the analysis tests below rely on the two
  // coded fixtures staying intact, so the delete lands on this one.
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [FILE_CTX]);
  const row = page.getByRole("row").filter({ hasText: "files_ctx.txt" });
  await expect(row).toBeVisible({ timeout: 20_000 });

  // The whole right-click surface is there, incl. the heavy entries
  // (asserted as present, not executed).
  await row.click({ button: "right" });
  const menu = page.getByRole("menu", { name: "File actions" });
  await expect(menu).toBeVisible({ timeout: 10_000 });
  for (const item of ["Details", "Rename…", "Edit memo…", "Delete", "Assign to case…", "Replace file…"]) {
    await expect(menu.getByRole("menuitem", { name: item })).toBeVisible();
  }

  // Rename through the prompt dialog.
  const renamed = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && /\/sources\/\d+$/.test(new URL(r.url()).pathname),
    { timeout: 15_000 },
  );
  page.once("dialog", (d) => void d.accept("ctx_renamed.txt"));
  await menu.getByRole("menuitem", { name: "Rename…" }).click();
  await renamed;
  await expect(page.getByRole("row").filter({ hasText: "ctx_renamed.txt" })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByRole("row").filter({ hasText: "files_ctx.txt" })).toHaveCount(0);

  // Delete through the confirm dialog.
  const renamedRow = page.getByRole("row").filter({ hasText: "ctx_renamed.txt" });
  await renamedRow.click({ button: "right" });
  const menu2 = page.getByRole("menu", { name: "File actions" });
  await expect(menu2).toBeVisible({ timeout: 10_000 });
  page.once("dialog", (d) => void d.accept());
  await menu2.getByRole("menuitem", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "ctx_renamed.txt" })).toHaveCount(0, {
    timeout: 10_000,
  });
});

// ---------------------------------------------------------------------------

test("sentiment report: lexicon scoring of coded segments", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Sentiment analysis", exact: true }).click();

  // The summary card shows the distribution chips (default scope=segments,
  // mode=lexicon) once the scoring response lands.
  await expect(page.getByText("Distribution", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Positive", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Negative", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Neutral", { exact: true }).first()).toBeVisible();

  // The coded segments are scored and listed: "bright/sunny" is positive,
  // "dark/gloomy" negative.
  await expect(page.getByText("Alpha weather bright sunny.")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Beta storm dark gloomy.")).toBeVisible();

  // The summary counts are real: at least one positive and one negative.
  const chipCount = async (label: string): Promise<number> => {
    const chip = page.getByText(label, { exact: true }).first();
    const countSpan = chip.locator("xpath=following-sibling::span[1]");
    await expect(countSpan).toBeVisible({ timeout: 10_000 });
    return Number(await countSpan.textContent());
  };
  expect(await chipCount("Positive")).toBeGreaterThanOrEqual(1);
  expect(await chipCount("Negative")).toBeGreaterThanOrEqual(1);
});

// ---------------------------------------------------------------------------

test("stats report: crosstab with a chi-square card", async ({ page }) => {
  await ensureProjectOpen(page);

  // Seed a file-scope attribute type + values through the API (the UI has
  // no value-label editor; same approach as roadmap.spec.ts).
  const sourcesRes = await page.request.get("http://localhost:8765/api/v1/sources");
  const sources = (await sourcesRes.json()) as { id: number; name: string }[];
  const fileA = sources.find((s) => s.name === "file_a.txt");
  const fileB = sources.find((s) => s.name === "file_b.txt");
  expect(fileA).toBeTruthy();
  expect(fileB).toBeTruthy();

  const typeRes = await page.request.post("http://localhost:8765/api/v1/attributes/types", {
    data: { name: "Region", case_or_file: "file", value_type: "text" },
  });
  expect(typeRes.ok()).toBeTruthy();
  for (const [fid, value] of [
    [fileA!.id, "north"],
    [fileB!.id, "south"],
  ] as const) {
    const setRes = await page.request.put(
      `http://localhost:8765/api/v1/attributes/values/Region?attr_type=file&entity_id=${fid}`,
      { data: { value } },
    );
    expect(setRes.ok()).toBeTruthy();
  }

  // The report picks the attribute automatically and runs the crosstab.
  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Statistics", exact: true }).click();
  const attr = page.getByLabel("Attribute");
  await expect(attr).toBeVisible({ timeout: 20_000 });
  await expect(attr.locator("option")).toContainText(["Region (file)"]);

  // Chi-square card + the contingency rows. (2x2 tables apply the Yates
  // correction, so the label reads "Chi-square (Yates-corrected)".)
  await expect(page.getByText("Crosstab", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/^Chi-square/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("row").filter({ hasText: "WaveCode" }).first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("north", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("south", { exact: true }).first()).toBeVisible();
});

// ---------------------------------------------------------------------------

test("summary table: file×code grid renders and a cell memo can be edited", async ({
  page,
}) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Summary table", exact: true }).click();

  // Grid: one row per file, one column per code (default scope "Files").
  await expect(page.getByText("Document", { exact: true }).first()).toBeVisible({
    timeout: 20_000,
  });
  const rowA = page.getByRole("row").filter({ hasText: "file_a.txt" });
  const rowB = page.getByRole("row").filter({ hasText: "file_b.txt" });
  await expect(rowA).toBeVisible({ timeout: 10_000 });
  await expect(rowB).toBeVisible();

  // Locate the WaveCode column by header text (codes are sorted by name).
  const headers = page.locator("thead th");
  let colIdx = -1;
  for (let i = 0; i < (await headers.count()); i++) {
    const txt = (await headers.nth(i).textContent()) ?? "";
    if (txt.trim() === "WaveCode") {
      colIdx = i;
      break;
    }
  }
  expect(colIdx).toBeGreaterThan(-1);

  // Edit the (file_a × WaveCode) cell: memo textarea + Save, then Done.
  const cell = rowA.locator("td").nth(colIdx);
  await cell.click();
  const memoInput = cell.getByLabel("Memo");
  await expect(memoInput).toBeVisible({ timeout: 10_000 });
  await memoInput.fill("Grid memo from the e2e wave");
  const patched = page.waitForResponse(
    (r) => r.request().method() === "PATCH" && /\/codings\/text\/\d+$/.test(new URL(r.url()).pathname),
    { timeout: 15_000 },
  );
  await cell.getByRole("button", { name: "Save", exact: true }).click();
  await patched;
  await cell.getByRole("button", { name: "Done", exact: true }).click();
  await expect(cell).toContainText("Grid memo from the e2e wave", { timeout: 10_000 });
});

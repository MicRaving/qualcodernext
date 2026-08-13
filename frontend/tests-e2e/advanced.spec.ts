/**
 * Advanced E2E scenarios against the REAL app: PDF region coding, duplicate
 * import handling, and persistence (theme + recent projects + error path).
 *
 * Runs in the same serial suite as app.spec.ts / features.spec.ts (workers:
 * 1, files run alphabetically — this file comes first). The backend process
 * persists across tests, so the project created in test 1 stays open; later
 * tests re-open it from the recent-projects list (fresh pages always land on
 * the welcome screen — the app has no session resume) using the same backend
 * quirks documented in features.spec.ts (lock file + `about` marker).
 */
import { expect, test, type Page } from "./helpers";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-e2e");
const PROJECT_PATH = path.join(E2E_ROOT, "Advanced.qda");
const DUP_TXT = path.join(E2E_ROOT, "dup.txt");
const PDF_PATH = path.join(E2E_ROOT, "e2e.pdf");
const MISSING_QDA = path.join(E2E_ROOT, "does-not-exist.qda");

/** Backend venv python — the only place PyMuPDF (fitz) is guaranteed to be. */
const BACKEND_PYTHON = path.resolve(
  process.cwd(),
  "..",
  "backend",
  ".venv",
  "Scripts",
  "python.exe",
);

/**
 * Generate the PDF fixture programmatically with the backend venv's PyMuPDF.
 * This is test infrastructure only (never runs inside the app process).
 */
function makePdfFixture(): void {
  const script = [
    "import fitz",
    "doc = fitz.open()",
    "page = doc.new_page(width=300, height=200)",
    "page.insert_text((50, 80), 'E2E PDF page')",
    `doc.save(${JSON.stringify(PDF_PATH)})`,
    "doc.close()",
  ].join("; ");
  try {
    execFileSync(BACKEND_PYTHON, ["-c", script], {
      stdio: "pipe",
      encoding: "utf-8",
    });
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    throw new Error(
      `Could not generate the PDF fixture via ${BACKEND_PYTHON} ` +
        `(is PyMuPDF installed in the backend venv?): ${detail}`,
    );
  }
  if (!fs.existsSync(PDF_PATH)) {
    throw new Error(`PDF fixture missing after generation: ${PDF_PATH}`);
  }
}

function ensureFixtureFiles() {
  // Fresh slate for OUR project only (app.spec.ts wipes E2E_ROOT wholesale at
  // its start, after this file has already run — leave its Study.qda alone).
  for (let i = 0; i < 10; i++) {
    fs.rmSync(i === 0 ? PROJECT_PATH : `${PROJECT_PATH}_${i}`, {
      recursive: true,
      force: true,
    });
  }
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(DUP_TXT, "some content", "utf-8");
  makePdfFixture();
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  ensureFixtureFiles();
});

/**
 * The backend's migration chain rewrites the project row's `about` field to
 * the bare app version on EVERY open, and `open_project` rejects a database
 * whose `about` lacks "QualCoder" — so a project can only be opened once per
 * backend session. Restore the marker directly (the backend's idle sqlite
 * connection does not block a quick UPDATE). Same quirk as features.spec.ts.
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
 * Make sure the Advanced project is open. Fresh pages land on the welcome
 * screen, so re-open from the recent-projects list; clear the backend's
 * stale lock file and repair the `about` marker first (see features.spec.ts
 * for the full quirk story).
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

// ---------------------------------------------------------------------------

test("PDF import and region coding", async ({ page }) => {
  // -------------------------------------------------------------- create
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await expect(dialog).toBeVisible();
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
    timeout: 30_000,
  });

  // --------------------------------------------------------------- import
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [PDF_PATH]);
  const row = page.getByRole("row").filter({ hasText: "e2e.pdf" });
  await expect(row).toBeVisible({ timeout: 20_000 });

  // Open the PDF in the coder (PDFs route to PdfCoder via isPdf).
  await row.click();

  // PdfCoder renders one page wrapper with role="img" "Page 1 of 1" and
  // sizes it once pdf.js reports the page geometry ("fit" zoom).
  const pimg = page.getByRole("img", { name: "Page 1 of 1" });
  await expect(pimg).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(async () => (await pimg.boundingBox())?.width ?? 0, { timeout: 15_000 })
    .toBeGreaterThan(100);

  // ----------------------------------------------------------------- drag
  const box = await pimg.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.2, box!.y + box!.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.6, box!.y + box!.height * 0.6, {
    steps: 5,
  });
  await page.mouse.up();

  // ---------------------------------------------------------------- code
  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("PdfCode");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });

  // The new coded region renders as an overlay with title "PdfCode"; click
  // it to select it — the details panel shows the code name + page.
  const region = page.locator('div[title="PdfCode"]');
  await expect(region).toBeVisible({ timeout: 10_000 });
  await region.click();
  await expect(page.getByText("Coding details")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("PdfCode", { exact: true })).toBeVisible();
  await expect(page.getByText(/Page 1 ·/)).toBeVisible();

  // --------------------------------------------------------------- delete
  // The details panel's Remove button deletes the coding (window.confirm).
  // features.spec.ts only asserts the image coder's Delete button exists —
  // it never clicks it, so the actual deletion path is exercised here.
  page.on("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Remove this coding" }).click();
  await expect(region).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByText("Coding details")).toBeHidden({ timeout: 10_000 });

  // ----------------------------------------------------------- plain text
  // PDFs must offer a plain-text mode: the extracted text is shown and can
  // be coded like any text document, then switched back to the rendered PDF.
  page.removeAllListeners("dialog");
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.getByText("E2E PDF page")).toBeVisible({ timeout: 20_000 });
  // The coder toolbar toggles are "Plain text" / "PDF" (exact — "PDF" is a
  // substring of every PdfCode/PdfTextCode row name in the sidebar).
  await expect(page.getByRole("button", { name: "PDF", exact: true })).toBeVisible();

  // Create a fresh code via the sidebar (Code → inline name editor).
  await page.getByRole("button", { name: "Code", exact: true }).click();
  const pdfCodeInput = page.getByTestId("inline-name-edit");
  await expect(pdfCodeInput).toBeVisible({ timeout: 10_000 });
  await pdfCodeInput.fill("PdfTextCode");
  await pdfCodeInput.press("Enter");
  await expect(page.getByRole("button", { name: "PdfTextCode", exact: true })).toBeVisible({
    timeout: 10_000,
  });

  const line = page.getByText("E2E PDF page");
  const lb = await line.boundingBox();
  expect(lb).not.toBeNull();
  // The locator resolves to the full-height document div; the first text
  // line sits just below the 24px (p-6) padding — drag across it.
  const y = lb!.y + 32;
  await page.mouse.move(lb!.x + 4, y);
  await page.mouse.down();
  await page.mouse.move(lb!.x + lb!.width - 4, y, { steps: 6 });
  await page.mouse.up();

  await page.getByRole("button", { name: "PdfTextCode", exact: true }).click();

  const tseg = page.locator('span[title="PdfTextCode"]');
  await expect(tseg).toBeVisible({ timeout: 10_000 });
  await tseg.click();
  await expect(page.getByText("Coding details")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("li").filter({ hasText: "PdfTextCode" })).toBeVisible();

  // Turn the text pane back off — the rendered PDF is the only view again.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.getByRole("img", { name: "Page 1 of 1" })).toBeVisible({
    timeout: 20_000,
  });
});
// ---------------------------------------------------------------------------

test("duplicate import shows the skip banner", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();

  await page.setInputFiles("input[type=file]", [DUP_TXT]);
  await expect(page.getByRole("row").filter({ hasText: "dup.txt" })).toBeVisible({
    timeout: 20_000,
  });

  // Re-importing the same file: the backend answers 409 and FileManager
  // shows the "Skipped: dup.txt (duplicate)" status banner.
  await page.setInputFiles("input[type=file]", [DUP_TXT]);
  await expect(
    page.getByRole("status").filter({ hasText: /Skipped: dup\.txt \(duplicate\)/ }),
  ).toBeVisible({ timeout: 20_000 });
});

// ---------------------------------------------------------------------------

test("theme preference persists across reload", async ({ page }) => {
  // The theme is stored in localStorage ("qc-theme") and applied to the
  // html class on load (the Settings toggle writes the same value).
  await page.goto("/");
  const initial = await page.locator("html").evaluate((el) =>
    el.classList.contains("dark"),
  );
  const target = initial ? "light" : "dark";

  await page.evaluate((m) => localStorage.setItem("qc-theme", m), target);
  await page.reload();
  if (target === "dark") {
    await expect(page.locator("html")).toHaveClass(/dark/);
  } else {
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  }

  // Flip back to the initial value: the preference still survives.
  await page.evaluate((m) => localStorage.setItem("qc-theme", m), initial ? "dark" : "light");
  await page.reload();
  if (initial) {
    await expect(page.locator("html")).toHaveClass(/dark/);
  } else {
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  }
});

// ---------------------------------------------------------------------------

test("recent projects persist after reload", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Recent projects", { exact: true })).toBeVisible({
    timeout: 10_000,
  });

  // Advanced.qda (created in test 1, re-opened since) is in the list.
  const recent = page.getByRole("button", { name: PROJECT_PATH, exact: true });
  await expect(recent).toBeVisible({ timeout: 10_000 });

  // Same backend-quirk workarounds as ensureProjectOpen before reopening.
  fs.rmSync(path.join(PROJECT_PATH, "project_in_use.lock"), { force: true });
  await repairProjectMeta();
  await recent.click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
    timeout: 30_000,
  });
});

// ---------------------------------------------------------------------------

test("open nonexistent project shows an error", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();

  await page.getByRole("button", { name: "Open project" }).click();
  const openDialog = page.getByRole("dialog", { name: "Open project" });
  await expect(openDialog).toBeVisible();
  await openDialog.locator("#open-path").fill(MISSING_QDA);
  await openDialog.getByRole("button", { name: "Open project" }).click();

  // The backend answers "project directory missing"; the welcome screen
  // renders it in a role="alert" box.
  await expect(page.getByRole("alert")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("alert")).toHaveText(/missing|not|error/i);

  // Leave the backend with NO project open: app.spec.ts wipes the whole
  // qc-e2e directory in its beforeAll, which fails with EPERM on Windows
  // while our Advanced.qda sqlite engine is still open.
  await page.request.post("http://localhost:8765/api/v1/projects/close");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
});

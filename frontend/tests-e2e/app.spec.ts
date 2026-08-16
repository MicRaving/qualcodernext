/**
 * E2E tests against the REAL app: FastAPI backend on :8765 + Vite frontend
 * on :5173, driven purely through the UI (no direct API calls).
 *
 * The servers are started by tests-e2e/global-setup.ts. Tests run serially
 * (single worker) because the backend holds one open project at a time and
 * writes shared user settings.
 */
import { expect, test } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-e2e");
const PROJECT_PATH = path.join(E2E_ROOT, "Study.qda");
const INTERVIEW_FILE = path.join(E2E_ROOT, "interview.txt");

async function ensureFixtureFiles() {
  // Fresh state for every run: wipe OUR project dir, then write the interview
  // fixture that later tests import. The backend keeps the other specs'
  // projects (Advanced.qda, Media.qda) open with locked handles, so wiping
  // E2E_ROOT wholesale fails on Windows — only Study.qda is ours.
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
      break;
    } catch {
      if (attempt === 19) throw new Error(`Could not wipe ${PROJECT_PATH}`);
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(
    INTERVIEW_FILE,
    "The participant was happy with the service.\nThe waiting time was too long.",
    "utf-8",
  );
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  await ensureFixtureFiles();
});

test("app shell with full dashboard (no welcome screen)", async ({ page }) => {
  await page.goto("/");

  // The full dashboard shows without a project: heading, stat placeholders
  // and New/Open enabled; the project nav buttons are present but disabled.
  await expect(page.getByRole("heading", { name: "QCnext" })).toBeVisible();
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open project" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Dashboard" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Coding", exact: true })).toBeDisabled();

  // No backend status indicator in the top bar during startup.
  await expect(page.getByRole("status")).toHaveCount(0);
});

test("create project, import a file, autocode it, and run a report", async ({ page }) => {
  await page.goto("/");

  // ---------------------------------------------------------------- create
  await test.step("create project from the dashboard", async () => {
    await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
    await page.getByRole("button", { name: "New project" }).click();
    const dialog = page.getByRole("dialog", { name: "New project" });
    await expect(dialog).toBeVisible();
    await dialog.locator("#create-path").fill(PROJECT_PATH);
    await dialog.getByRole("button", { name: "Create project" }).click();

    // Project shell replaces the dashboard empty state.
    await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("button", { name: "Coding", exact: true })).toBeVisible();
  });

  // ----------------------------------------------------------------- import
  await test.step("import a text file and open it in the coder", async () => {
    await page.getByRole("button", { name: "Coding", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();

    await page.setInputFiles("input[type=file]", INTERVIEW_FILE);

    const row = page.getByRole("row").filter({ hasText: "interview.txt" });
    await expect(row).toBeVisible({ timeout: 20_000 });
    await row.click();

    // Coding workspace shows the document text.
    await expect(page.getByText("The participant was happy with the service.")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("The waiting time was too long.")).toBeVisible();
  });

  // --------------------------------------------------------------- autocode
  await test.step("autocode the document into a new code", async () => {
    // Create the code first (sidebar inline editor).
    await page.getByRole("button", { name: "Code", exact: true }).click();
    await page.getByTestId("inline-name-edit").fill("E2E");
    await page.keyboard.press("Enter");
    await expect(page.getByText("E2E", { exact: true }).first()).toBeVisible({
      timeout: 10_000,
    });

    await page.getByRole("button", { name: "Autocode" }).first().click();
    const dialog = page.getByRole("dialog", { name: "Autocode" });
    const promptBox = dialog.getByLabel("Coding prompt");
    await expect(promptBox).toBeVisible();
    await promptBox.fill('"happy"');
    await dialog.getByText("E2E").click();
    // The dialog gained a "Autocode with dictionary" button — the main action
    // must be matched exactly so the two never collide.
    await dialog.getByRole("button", { name: "Autocode", exact: true }).click();

    await expect(dialog.getByText(/Autocoded \d+ instances/)).toBeVisible({
      timeout: 20_000,
    });
  });

  // ----------------------------------------------------------------- report
  await test.step("code frequencies report shows the new code", async () => {
    await page.getByRole("button", { name: "Reports", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();

    await page.getByRole("button", { name: /Code frequencies/ }).click();

    const freqRow = page.getByRole("row").filter({ hasText: "E2E" });
    await expect(freqRow).toBeVisible({ timeout: 20_000 });
    const countText = await freqRow.locator("td").nth(2).innerText();
    expect(Number.parseInt(countText, 10)).toBeGreaterThanOrEqual(1);
  });

  // --------------------------------------------------------------- close out
  await test.step("close the project; it appears in recent projects", async () => {
    await page.request.post("http://localhost:8765/api/v1/projects/close");
    await page.goto("/");
    await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
    await expect(page.getByText("Recent projects", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: PROJECT_PATH, exact: true })).toBeVisible();
  });
});

test("settings and AI status", async ({ page }) => {
  await page.goto("/");

  // Re-open the project from the recent-projects list created by the
  // previous test, then navigate to Settings.
  const recent = page.getByRole("button", { name: PROJECT_PATH, exact: true });
  await expect(recent).toBeVisible();
  await recent.click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByText("Appearance", { exact: true })).toBeVisible();

  // Settings are grouped into tabs — the AI section lives on the AI tab.
  await page.getByRole("tab", { name: "AI", exact: true }).click();
  await expect(page.getByText("AI assistant", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Updates", exact: true }).click();
  await expect(page.getByText("Auto-update", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Check interval", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Maintenance", exact: true }).click();
  await expect(page.getByText("Compact project", { exact: true })).toBeVisible();
});

/**
 * E2E tests against the REAL app: FastAPI backend on :8765 + Vite frontend
 * on :5173, driven purely through the UI (no direct API calls).
 *
 * The servers are started by tests-e2e/global-setup.ts. Tests run serially
 * (single worker) because the backend holds one open project at a time and
 * writes shared user settings.
 */
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-e2e");
const PROJECT_PATH = path.join(E2E_ROOT, "Study.qda");
const INTERVIEW_FILE = path.join(E2E_ROOT, "interview.txt");

async function ensureFixtureFiles() {
  // Fresh state for every run: wipe any leftover test project, then write
  // the interview fixture that later tests import. A previous run's servers
  // may still hold handles on the dir (global-setup kills them first, so
  // this is only a belt-and-braces retry).
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      fs.rmSync(E2E_ROOT, { recursive: true, force: true });
      break;
    } catch {
      if (attempt === 19) throw new Error(`Could not wipe ${E2E_ROOT}`);
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

test("welcome screen and theme toggle", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "QualCoder" })).toBeVisible();

  // Backend health pill: the app calls GET /api/v1/health on mount.
  await expect(page.getByRole("status").first()).toHaveText(/Backend ok/);

  // Theme toggle: flips the `dark` class on <html> and switches its label.
  const toggle = page.getByRole("button", { name: /Switch to (dark|light) theme/ });
  await expect(toggle).toBeVisible();
  const startsDark = (await toggle.getAttribute("aria-label")) === "Switch to light theme";

  await toggle.click();

  if (startsDark) {
    await expect(page.locator("html")).not.toHaveClass(/dark/);
    await expect(toggle).toHaveAttribute("aria-label", "Switch to dark theme");
  } else {
    await expect(page.locator("html")).toHaveClass(/dark/);
    await expect(toggle).toHaveAttribute("aria-label", "Switch to light theme");
  }
});

test("create project, import a file, autocode it, and run a report", async ({ page }) => {
  await page.goto("/");

  // ---------------------------------------------------------------- create
  await test.step("create project from the dashboard", async () => {
    await expect(page.getByRole("heading", { name: "QualCoder" })).toBeVisible();
    await page.getByRole("button", { name: "New project" }).click();
    const dialog = page.getByRole("dialog", { name: "New project" });
    await expect(dialog).toBeVisible();
    await dialog.locator("#create-path").fill(PROJECT_PATH);
    await dialog.getByRole("button", { name: "Create project" }).click();

    // Project shell replaces the dashboard empty state.
    await expect(page.getByRole("button", { name: "Go to code" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByRole("button", { name: "Files" })).toBeVisible();
  });

  // ----------------------------------------------------------------- import
  await test.step("import a text file and open it in the coder", async () => {
    await page.getByRole("button", { name: "Files" }).click();
    await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();

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
    await page.getByRole("button", { name: "Autocode" }).first().click();

    const searchText = page.getByPlaceholder("One search text per line");
    await expect(searchText).toBeVisible();
    await searchText.fill("happy");
    await page.getByPlaceholder("\u2026or new code name").fill("E2E");

    // The panel's run button is the second "Autocode" button in DOM order.
    await page.getByRole("button", { name: "Autocode" }).nth(1).click();

    await expect(page.getByText(/Autocoded \d+ instances/)).toBeVisible({ timeout: 20_000 });
  });

  // ----------------------------------------------------------------- report
  await test.step("code frequencies report shows the new code", async () => {
    await page.getByRole("button", { name: "Reports" }).click();
    await expect(page.getByRole("heading", { name: "Analysis" })).toBeVisible();

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
    await expect(page.getByRole("heading", { name: "QualCoder" })).toBeVisible();
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
  await expect(page.getByRole("button", { name: "Go to code" })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByText("Appearance", { exact: true })).toBeVisible();
  await expect(page.getByText("AI assistant", { exact: true })).toBeVisible();
});

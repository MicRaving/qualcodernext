/**
 * Background-task queue + accessibility + layout E2E:
 * - Files view batch Autocode queues background tasks; the flyout offers
 *   pause/resume, per-task delete (trashcan) and clear.
 * - Sidebars hide when dragged far past the minimum width and are recalled
 *   via the edge arrow.
 * - The display-mode drop-down (dashboard + settings) applies a11y classes.
 * - PDF coder: side-by-side PDF + plain-text split view.
 */
import { expect, test } from "@playwright/test";
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-tasks");
const unique = (name: string) =>
  path.join(E2E_ROOT, `${name}_${Date.now() % 100000}_${Math.floor(Math.random() * 999)}.qda`);

const BACKEND_PYTHON = (() => {
  const venv = path.resolve(process.cwd(), "..", "backend", ".venv", "Scripts", "python.exe");
  return fs.existsSync(venv) ? venv : "python";
})();

async function createProject(page: import("@playwright/test").Page, projectPath: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(projectPath);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
  // The dialog may linger while the backend warms up — wait until it is gone
  // so it never blocks later clicks (the modal overlay intercepts them).
  await expect(dialog).toBeHidden({ timeout: 30_000 });
}

test("files-view batch autocode queues background tasks with queue controls", async ({ page }) => {
  const projectPath = unique("Tk");
  const aPath = path.join(E2E_ROOT, `a_${Date.now() % 100000}.txt`);
  const bPath = path.join(E2E_ROOT, `b_${Date.now() % 100000}.txt`);
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(aPath, "cat dog cat bird\n", "utf-8");
  fs.writeFileSync(bPath, "mouse cat dog\n", "utf-8");

  await createProject(page, projectPath);
  await page.getByRole("button", { name: "Coding", exact: true }).click();

  // Import both text files.
  await page.setInputFiles("input[type=file]", [aPath, bPath]);
  await expect(page.getByRole("row").filter({ hasText: "a_" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("row").filter({ hasText: "b_" })).toBeVisible({ timeout: 20_000 });

  // Create a code first (the autocode dialog needs at least one code).
  await page.getByRole("row").filter({ hasText: "a_" }).click();
  await expect(page.getByRole("button", { name: "Code", exact: true })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("button", { name: "Code", exact: true }).click();
  await page.getByTestId("inline-name-edit").fill("CatCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("CatCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

  // Back to the files view and select both rows.
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  const rowA = page.getByRole("row").filter({ hasText: "a_" });
  const rowB = page.getByRole("row").filter({ hasText: "b_" });
  await rowA.locator('input[type="checkbox"]').check();
  await rowB.locator('input[type="checkbox"]').check();

  // The batch buttons appear with the selection counts (eligible/total):
  // Transcribe only counts AV media (none here → disabled), Autocode counts
  // text sources (both → enabled).
  const transcribeBtn = page.getByRole("button", { name: "Transcribe (0/2)" });
  const autocodeBtn = page.getByRole("button", { name: "Autocode (2/2)" });
  await expect(transcribeBtn).toBeVisible();
  await expect(transcribeBtn).toBeDisabled();
  await expect(autocodeBtn).toBeVisible();
  await expect(autocodeBtn).toBeEnabled();

  // Autocode dialog: select the code, the prompt prefills with the code name.
  await autocodeBtn.click();
  const dialog = page.getByRole("dialog", { name: "Autocode" });
  await expect(dialog).toBeVisible();
  await dialog.getByText("CatCode", { exact: true }).click();
  await expect(dialog.locator('input[type="checkbox"]').first()).toBeChecked();
  await expect
    .poll(async () => (await dialog.getByLabel("Coding prompt").inputValue()).includes("CatCode"), {
      timeout: 5_000,
    })
    .toBe(true);
  // The dialog also has a "Autocode with dictionary" button — match the main
  // action exactly so the two never collide.
  await dialog.getByRole("button", { name: "Autocode", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });

  // Both files are queued as background tasks in the ribbon flyout.
  const queue = page.getByRole("button", { name: "Background tasks" });
  await expect(queue).toBeVisible();
  await queue.click();
  const flyout = page.locator('[role="menu"]');
  await expect(flyout.getByText(/a_\d+\.txt/)).toBeVisible();
  await expect(flyout.getByText(/b_\d+\.txt/)).toBeVisible();

  // Pause/resume toggle exists and toggles.
  const pauseBtn = page.getByRole("button", { name: "Pause queue" });
  await expect(pauseBtn).toBeVisible();
  await pauseBtn.click();
  await expect(page.getByText("Queue paused — tasks start when resumed.")).toBeVisible();
  await page.getByRole("button", { name: "Resume queue" }).click();
  await expect(page.getByText("Queue paused — tasks start when resumed.")).toBeHidden();

  // Both jobs complete (AI is off → literal match fallback, fast).
  await expect(flyout.getByText("✓")).toHaveCount(2, { timeout: 120_000 });

  // Per-task trashcan removes one entry.
  await flyout.getByRole("button", { name: /Remove task for b_/ }).click();
  await expect(flyout.getByText(/b_\d+\.txt/)).toHaveCount(0);

  // Clear removes the remaining finished task.
  await page.getByRole("button", { name: "Clear finished tasks" }).click();
  await expect(flyout.getByText(/a_\d+\.txt/)).toHaveCount(0);
});

test("coder flyout stays in the viewport and hosts per-row delete + background tasks", async ({
  page,
}) => {
  const projectPath = unique("Fl");
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  await createProject(page, projectPath);

  // The flyout opens from the coder-switcher button in the ribbon.
  const coderBtn = page.getByRole("button", { name: /click to switch/ });
  await expect(coderBtn).toBeVisible();
  await coderBtn.click();
  const flyout = page.getByRole("listbox", { name: "Coders" });
  await expect(flyout).toBeVisible();

  // Window-bounds sanity: the flyout must stay fully inside the viewport
  // (the positioning code clamps it with an 8px margin on every side).
  const box = await flyout.boundingBox();
  expect(box).not.toBeNull();
  const vp = page.viewportSize();
  expect(vp).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(vp!.width);
  expect(box!.y + box!.height).toBeLessThanOrEqual(vp!.height);

  // Per-coder rows carry a trashcan (Delete) button; the CURRENT coder's
  // delete is disabled ("switch to another coder first").
  const currentRow = flyout.getByRole("option").filter({ hasText: "default" });
  await expect(currentRow).toBeVisible();
  await expect(currentRow.getByRole("button", { name: "Delete", exact: true })).toBeDisabled();

  // Add a second coder — the app switches to it, so its row now carries the
  // enabled trashcan while the previous (default) coder's becomes deletable.
  await flyout.getByRole("button", { name: /Add coder/ }).click();
  await flyout.getByRole("textbox", { name: "New coder name" }).fill("Second");
  await flyout.getByRole("button", { name: "Add coder" }).click();
  const secondRow = flyout.getByRole("option").filter({ hasText: "Second" });
  await expect(secondRow).toBeVisible({ timeout: 10_000 });
  await expect(secondRow.getByRole("button", { name: "Delete", exact: true })).toBeVisible();

  // Deleting the now non-current coder removes its row entirely.
  const defaultRow = flyout.getByRole("option").filter({ hasText: "default" });
  await expect(defaultRow.getByRole("button", { name: "Delete", exact: true })).toBeEnabled();
  await defaultRow.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(defaultRow).toHaveCount(0, { timeout: 10_000 });

  // The flyout hosts the background-tasks section with its queue controls.
  await expect(flyout.getByText("Background tasks", { exact: true })).toBeVisible();
  await expect(flyout.getByText("No background tasks.")).toBeVisible();
  await expect(flyout.getByRole("button", { name: "Start", exact: true })).toBeVisible();
  await expect(flyout.getByRole("button", { name: "Pause", exact: true })).toBeVisible();
  await expect(flyout.getByRole("button", { name: "Clear all", exact: true })).toBeVisible();
});

test("sidebars hide when dragged past the minimum and recall via edge arrow", async ({ page }) => {
  const projectPath = unique("Sb");
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  await createProject(page, projectPath);

  const separator = page.getByRole("separator", { name: "Resize left sidebar" });
  await expect(separator).toBeVisible();
  const box = await separator.boundingBox();
  expect(box).not.toBeNull();

  // Drag the handle far left — way past the 200px minimum.
  await page.mouse.move(box!.x + box!.width / 2, box!.y + 200);
  await page.mouse.down();
  await page.mouse.move(box!.x - 500, box!.y + 200, { steps: 10 });
  await page.mouse.up();

  // The sidebar is hidden; the edge arrow offers recall.
  const recall = page.getByRole("button", { name: "Show left sidebar" });
  await expect(recall).toBeVisible({ timeout: 5_000 });
  await expect(separator).toHaveCount(0);

  await recall.click();
  await expect(separator).toBeVisible({ timeout: 5_000 });
  await expect(page.getByRole("button", { name: "Show left sidebar" })).toHaveCount(0);
});

test("display-mode drop-down applies a11y classes (dashboard + settings)", async ({ page }) => {
  await page.goto("/");
  const dashboardSelect = page.getByLabel("Display mode");
  await expect(dashboardSelect).toBeVisible({ timeout: 15_000 });

  await dashboardSelect.selectOption("high-contrast");
  await expect(page.locator("html")).toHaveClass(/a11y-high-contrast/);

  // Settings exposes the same drop-down (the dashboard one stays mounted
  // behind it — target the settings instance).
  await page.getByRole("button", { name: "Settings" }).click();
  const settingsSelect = page.getByLabel("Display mode").last();
  await expect(settingsSelect).toBeVisible({ timeout: 10_000 });
  await settingsSelect.selectOption("screenreader");
  await expect(page.locator("html")).toHaveClass(/a11y-screenreader/);

  // Reset to standard.
  await settingsSelect.selectOption("off");
  await expect(page.locator("html")).not.toHaveClass(/a11y-(high-contrast|screenreader)/);
});

test("pdf coder plain-text pane shows PDF and text side by side", async ({ page }) => {
  const projectPath = unique("Ps");
  const pdfPath = path.join(E2E_ROOT, `sb_${Date.now() % 100000}.pdf`);
  const script = `
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "The quick brown fox jumps over the lazy dog.")
page.insert_text((72, 130), "Another line of important research text here.")
doc.save(r"${pdfPath}")
`;
  const scriptPath = path.join(E2E_ROOT, `make_sb_${Date.now() % 100000}.py`);
  fs.writeFileSync(scriptPath, script, "utf-8");
  execSync(`"${BACKEND_PYTHON}" "${scriptPath}"`);

  fs.mkdirSync(E2E_ROOT, { recursive: true });
  await createProject(page, projectPath);
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [pdfPath]);
  await expect(page.getByRole("row").filter({ hasText: "sb_" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("row").filter({ hasText: "sb_" }).click();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);

  // The "Plain text" toggle is a pane switch (PDF stays on): pressing it
  // once shows the extracted text next to the canvas.
  const plainBtn = page.getByRole("button", { name: "Plain text" });
  await expect(plainBtn).toBeVisible();
  await plainBtn.click();
  await expect(plainBtn).toHaveAttribute("aria-pressed", "true");

  // The plain-text column renders next to the canvas; the divider exists.
  await expect(page.getByText("The quick brown fox jumps over the lazy dog.")).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("separator", { name: "Resize text panel" })).toBeVisible();

  // Toggling off removes the text column again.
  await plainBtn.click();
  await expect(page.getByText("The quick brown fox jumps over the lazy dog.")).toHaveCount(0, {
    timeout: 15_000,
  });
  await expect(page.locator("canvas").first()).toBeVisible();
});

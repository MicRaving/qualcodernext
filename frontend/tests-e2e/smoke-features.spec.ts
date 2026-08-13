/* Smoke: reports menu bar, graphs under reports, journal ribbon. */
import { expect, test } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-tabtest");
const PROJECT_PATH = path.join(E2E_ROOT, `Smoke_${Date.now() % 100000}.qda`);
const TXT = path.join(E2E_ROOT, "doc.txt");

test.beforeAll(() => {
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(TXT, "Some words here for coding.\n", "utf-8");
});

test("reports menu bar + graphs under reports + journal ribbon", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });

  // Reports view: the center menu bar shows the report's buttons
  // (Codebook always has export actions, even without data).
  await page.getByRole("button", { name: "Reports" }).click();
  await page.getByRole("button", { name: /Codebook/ }).click();
  await expect(page.getByRole("button", { name: /Download codebook/ })).toBeVisible({
    timeout: 15_000,
  });

  // Graphs under Reports: left-bar entry switches the center to the editor,
  // which shows the graph dropdown + Add button (right).
  await page.getByRole("button", { name: "Graphs", exact: true }).click();
  await expect(page.getByLabel("Select graph…")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeVisible();

  // Journal ribbon: the notes view shows the journal list (no tab dropdown).
  await page.getByRole("button", { name: "Journal" }).click();
  await expect(page.getByRole("button", { name: "Add", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Notes sections" })).toHaveCount(0);
});

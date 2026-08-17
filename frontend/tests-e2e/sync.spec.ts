/* Collaboration sync (Option B) e2e: the coder-flyout sync switch, the
 * "Sync now" action, the status indicator, and the shared-folder auto-detect
 * notice. Backend unit tests cover the replay/conflict/atomicity logic; this
 * exercises the frontend flow end to end. */
import { expect, test } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-synctest");
const PLAIN_PROJECT = path.join(E2E_ROOT, `Sync_${Date.now() % 100000}.qda`);
const CLOUD_PROJECT = path.join(E2E_ROOT, "OneDrive", `Cloud_${Date.now() % 100000}.qda`);

const BACKEND = "http://localhost:8765";

async function createProject(page: import("@playwright/test").Page, projectPath: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(projectPath);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
}

async function openCoderFlyout(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: /Current coder:/ }).click();
  await expect(page.getByRole("switch", { name: "Enable background sync" })).toBeVisible();
}

test("sync toggle, status and Sync now in the coder flyout", async ({ page }) => {
  await createProject(page, PLAIN_PROJECT);
  await openCoderFlyout(page);

  const toggle = page.getByRole("switch", { name: "Enable background sync" });
  await expect(toggle).toHaveAttribute("aria-checked", "false");

  // Toggle sync on; the status block renders and the indicator appears.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "true");

  // The "Sync now" button is present. (Toggling on runs an immediate cycle,
  // so it may already show a relative time rather than "Never".)
  const syncNow = page.getByRole("button", { name: /ago|Sync now|Never/ });
  await expect(syncNow).toBeVisible();

  // A manual sync runs without error and updates the last-sync time.
  await syncNow.click();
  await expect(page.getByRole("button", { name: /ago/ })).toBeVisible({ timeout: 15_000 });

  // Toggle off restores the off state.
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", "false");
});

test("shared-folder auto-detect shows the collaboration notice", async ({ page }) => {
  // The project lives under a "OneDrive" path, which the backend flags as a
  // cloud-sync folder; opening it auto-enables sync and shows the notice.
  await createProject(page, CLOUD_PROJECT);
  await page.request.post(`${BACKEND}/api/v1/projects/close`);

  await page.goto("/");
  await page.getByRole("button", { name: "Open project" }).click();
  const openDialog = page.getByRole("dialog", { name: "Open project" });
  await openDialog.locator("#open-path").fill(CLOUD_PROJECT);
  await openDialog.getByRole("button", { name: "Open project" }).click();

  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByText("Collaboration sync enabled", { exact: false }),
  ).toBeVisible({ timeout: 10_000 });
});

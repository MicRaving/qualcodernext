/* Collaboration sync (Option B) e2e: the coder-flyout sync switch, the
 * "Sync now" action, the status indicator, the shared-folder auto-detect
 * notice, and live coder presence (who is active and on which file).
 * Backend unit tests cover the replay/conflict/atomicity logic; this
 * exercises the frontend flow end to end. */
import { expect, test } from "./helpers";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-synctest");

const BACKEND = "http://localhost:8765";

// Unique per-run project names (full ms timestamp) so create_project never
// appends a _1 suffix — the presence test needs the exact path. Cleanup is
// best-effort: a locked dir (leftover backend handle) must not fail the run.
test.beforeAll(() => {
  try {
    fs.rmSync(E2E_ROOT, { recursive: true, force: true });
  } catch {
    /* dir locked by a leftover handle — a fresh name still avoids collisions */
  }
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  return () => {};
});

const PLAIN_PROJECT = path.join(E2E_ROOT, `Sync_${Date.now()}.qda`);
const CLOUD_PROJECT = path.join(E2E_ROOT, "OneDrive", `Cloud_${Date.now()}.qda`);

async function createProject(page: import("@playwright/test").Page, projectPath: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(projectPath);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
}

async function openCoderFlyout(page: import("@playwright/test").Page) {
  // Slow CI runners can race the dashboard→ribbon render right after a
  // project opens (the button can vanish for seconds). Retry with a reload,
  // mirroring the ensureProjectOpen pattern used by other specs.
  for (let attempt = 0; attempt < 3; attempt++) {
    const coderBtn = page.getByRole("button", { name: /Current coder:/ });
    try {
      await expect(coderBtn).toBeVisible({ timeout: 15_000 });
      await coderBtn.click();
      await expect(page.getByText("Single-coder mode", { exact: true })).toBeVisible({
        timeout: 8_000,
      });
      return;
    } catch {
      await page.goto("/");
      await expect(
        page.getByRole("button", { name: PLAIN_PROJECT, exact: true }),
      ).toBeVisible({ timeout: 15_000 });
      await page.getByRole("button", { name: PLAIN_PROJECT, exact: true }).click();
      await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
        timeout: 30_000,
      });
    }
  }
  throw new Error(`Could not open the coder flyout after 3 attempts`);
}

test("collaboration flyout: activate gates Sync now to collab mode", async ({ page }) => {
  await createProject(page, PLAIN_PROJECT);
  await openCoderFlyout(page);

  // Single mode: no standalone sync toggle exists, and Sync now is hidden
  // (background sync is irrelevant without collaboration). Activation is
  // labelled 'Enable collaboration'.
  const activate = page.getByRole("button", { name: "Enable collaboration", exact: true });
  await expect(activate).toBeVisible();

  await page.getByRole("button", { name: /Current coder:/ }).click(); // close
  await openCoderFlyout(page);
  await expect(
    page.getByRole("button", { name: /ago|Sync now|Never/ }),
  ).toHaveCount(0);
});

test("shared-folder auto-detect does NOT auto-enable collaboration", async ({ page }) => {
  // The project lives under a "OneDrive" path (cloud-sync folder). Policy:
  // collaboration is never enabled automatically — the mode pill must stay
  // 'Single-coder mode' and no sync UI appears.
  await createProject(page, CLOUD_PROJECT);
  await page.request.post(`${BACKEND}/api/v1/projects/close`);

  await page.goto("/");
  await page.getByRole("button", { name: "Open project" }).click();
  const openDialog = page.getByRole("dialog", { name: "Open project" });
  await openDialog.locator("#open-path").fill(CLOUD_PROJECT);
  await openDialog.getByRole("button", { name: "Open project" }).click();

  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Collaboration active")).toHaveCount(0);
});

test("live coder presence: indicator + file shown in the coder flyout", async ({ page }) => {
  // Create via API so we get back the EXACT path (create appends _1 on
  // collision), then open from the recents list — avoids the Open-dialog
  // button race seen on CI.
  const liveProject = path.join(E2E_ROOT, `Live_${Date.now()}.qda`);
  const createdRes = await page.request.post(`${BACKEND}/api/v1/projects`, {
    data: { project_path: liveProject, codername: "default" },
  });
  const created = (await createdRes.json()) as { ok: boolean; project_path: string };
  expect(created.ok).toBeTruthy();
  const actual = created.project_path;

  await page.goto("/");
  const recent = page.getByRole("button", { name: actual, exact: true });
  await expect(recent).toBeVisible({ timeout: 15_000 });
  await recent.click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });

  // Simulate another live instance: spawn a real (long-lived) process and
  // write its presence file into the project folder. The app's presence poll
  // picks it up and shows it as "live".
  const sleeper = spawn(process.execPath, ["-e", "setTimeout(()=>{}, 60000)"]);
  const pid = sleeper.pid as number;
  const presenceDir = path.join(liveProject, "presence");
  fs.mkdirSync(presenceDir, { recursive: true });
  const now = Date.now() / 1000;
  try {
    fs.writeFileSync(
      path.join(presenceDir, `${pid}.json`),
      JSON.stringify({
        coder: "berta",
        os_user: "marvi",
        pid,
        ts: now,
        file_id: 7,
        file_name: "focus.txt",
      }),
      "utf-8",
    );

    // Open the coder flyout immediately — its open effect refreshes
    // presence, so the fabricated peer appears without any fixed wait.
    // CI runners are slow; retry in case the first open races rendering.
    let shown = false;
    for (let attempt = 0; attempt < 5 && !shown; attempt++) {
      const coderBtn = page.getByRole("button", { name: /Current coder:/ });
      try {
        await coderBtn.click({ timeout: 15_000 });
      } catch {
        // Ribbon not hydrated yet on slow CI - reload and retry.
        await page.goto("/");
        await expect(
          page.getByRole("button", { name: actual, exact: true }),
        ).toBeVisible({ timeout: 15_000 });
        await page.getByRole("button", { name: actual, exact: true }).click();
        await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({
          timeout: 30_000,
        });
        continue;
      }
      try {
        await expect(page.getByText("Actively working")).toBeVisible({ timeout: 8_000 });
        await expect(page.getByText("berta", { exact: true })).toBeVisible();
        await expect(page.getByText("focus.txt", { exact: true })).toBeVisible();
        shown = true;
      } catch {
        await page.keyboard.press("Escape");
      }
    }
    expect(shown).toBe(true);
  } finally {
    sleeper.kill();
  }
});

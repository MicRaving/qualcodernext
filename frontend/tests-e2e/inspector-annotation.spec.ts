/* Standalone repro: Inspector (files rightbar) — add annotation via the + button. */
import { expect, test } from "./helpers";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-tabtest");
const PROJECT_PATH = path.join(E2E_ROOT, `Insp_${Date.now() % 100000}.qda`);
const TXT_A = path.join(E2E_ROOT, "aaa.txt");

test.beforeAll(() => {
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  // Warm CI runners can keep %TEMP% between runs — a leftover project with
  // the same Date.now()%100000 name would make create_project append _1.
  fs.rmSync(PROJECT_PATH, { recursive: true, force: true });
  fs.writeFileSync(TXT_A, "File A content words.\n", "utf-8");
});

test("inspector: add annotation from the files rightbar", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "New project" })).toBeVisible();
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await expect(dialog).toBeVisible();
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Coding" }).first()).toBeVisible();
  await page.setInputFiles("input[type=file]", [TXT_A]);
  await expect(page.getByRole("row").filter({ hasText: "aaa.txt" })).toBeVisible({
    timeout: 20_000,
  });

  // Select the file → the rightbar inspector opens with its details.
  await page.getByRole("row").filter({ hasText: "aaa.txt" }).click();
  await expect(page.getByRole("heading", { name: "aaa.txt" }).nth(1)).toBeVisible({
    timeout: 10_000,
  });

  // Add annotation via the "+" button in the Annotations section.
  const addAnn = page.getByRole("button", { name: "Add annotation" }).first();
  await expect(addAnn).toBeVisible({ timeout: 10_000 });
  await addAnn.click();
  const box = page.getByLabel("Annotation memo", { exact: true });
  await expect(box).toBeVisible({ timeout: 10_000 });
  await box.fill("inspector note");
  await page.getByRole("button", { name: "Add annotation", exact: true }).last().click();
  await expect(page.getByText("inspector note")).toBeVisible({ timeout: 10_000 });
});

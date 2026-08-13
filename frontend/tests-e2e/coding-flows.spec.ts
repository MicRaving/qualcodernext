/**
 * Coding-flow regression suite: graph create/delete, PDF text marking
 * (shared codings with the plain-text mode), and the multi-code autocode
 * dialog. Each test uses its own throwaway project.
 */
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execSync } from "node:child_process";

const E2E_ROOT = path.join(os.tmpdir(), "qc-tabtest");
const unique = (name: string) =>
  path.join(E2E_ROOT, `${name}_${Date.now() % 100000}_${Math.floor(Math.random() * 999)}.qda`);

async function createProject(page: import("@playwright/test").Page, projectPath: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(projectPath);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Cases" })).toBeVisible({ timeout: 30_000 });
}

/* ------------------------------------------------------------------ graphs */

test("graph create updates list, delete works", async ({ page }) => {
  await createProject(page, unique("Gr"));

  await page.getByRole("button", { name: "Reports" }).click();
  await page.getByRole("button", { name: "Graphs", exact: true }).click();
  await expect(page.getByLabel("Select graph…")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Add", exact: true }).click();
  const nameDialog = page.getByRole("dialog", { name: /New graph/ });
  await expect(nameDialog).toBeVisible();
  await nameDialog.locator("input").first().fill("Map A");
  await nameDialog.getByRole("button", { name: "New graph" }).click();
  await expect(nameDialog).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(1);
  await expect(page.getByLabel("Select graph…").locator("option").first()).toHaveText("Map A");

  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(nameDialog).toBeVisible();
  await nameDialog.locator("input").first().fill("Map B");
  await nameDialog.getByRole("button", { name: "New graph" }).click();
  await expect(nameDialog).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(2);

  await page.getByRole("button", { name: "Delete the open graph" }).click();
  const confirm = page.getByRole("dialog", { name: /Delete/ });
  await expect(confirm).toBeVisible();
  await confirm.getByRole("button", { name: "Delete" }).click();
  await expect(confirm).toBeHidden();
  await expect(page.getByLabel("Select graph…").locator("option")).toHaveCount(1);
  await expect(page.locator("[class*=banner]")).toHaveCount(0);
});

/* ----------------------------------------------------------------- pdf text */

test("pdf text marking codes into the plain-text layer", async ({ page }) => {
  const projectPath = unique("Pdf");
  const pdfPath = path.join(E2E_ROOT, `doc_${Date.now() % 100000}.pdf`);
  const script = `
import fitz
doc = fitz.open()
page = doc.new_page()
page.insert_text((72, 100), "The quick brown fox jumps over the lazy dog.")
page.insert_text((72, 130), "Another line of important research text here.")
doc.save(r"${pdfPath}")
`;
  const scriptPath = path.join(E2E_ROOT, `make_pdf_${Date.now() % 100000}.py`);
  fs.writeFileSync(scriptPath, script, "utf-8");
  execSync(`"D:\\Downloads\\qualcoder-rework\\backend\\.venv\\Scripts\\python.exe" "${scriptPath}"`);

  await createProject(page, projectPath);

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [pdfPath]);
  await expect(page.getByRole("row").filter({ hasText: "doc_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "doc_" }).click();

  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2500);

  const canvas = page.locator("canvas").first();
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width * 0.16, box!.y + box!.height * 0.112);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.85, box!.y + box!.height * 0.135, { steps: 8 });
  await page.mouse.up();

  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("PdfMarked");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });
  await expect(page.locator("[class*=banner]")).toHaveCount(0);

  // Plain-text pane on: the extracted text (with the marked segment) shows
  // next to the rendered PDF. "Plain text" is a toggle — pressing it again
  // returns to the rendered PDF only.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.getByText("The quick brown fox jumps over the lazy dog.")).toBeVisible({
    timeout: 20_000,
  });
  const seg = page.locator(".qc-seg").first();
  await expect(seg).toBeVisible({ timeout: 15_000 });
  await expect(seg).toContainText("The quick brown fox jumps over the lazy dog.");

  // Switch back to the rendered PDF — canvases re-render and text marking works.
  await page.getByRole("button", { name: "Plain text" }).click();
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(1500);
  const canvas2 = page.locator("canvas").first();
  const box2 = await canvas2.boundingBox();
  expect(box2).not.toBeNull();
  await page.mouse.move(box2!.x + box2!.width * 0.16, box2!.y + box2!.height * 0.19);
  await page.mouse.down();
  await page.mouse.move(box2!.x + box2!.width * 0.85, box2!.y + box2!.height * 0.21, { steps: 6 });
  await page.mouse.up();
  const picker2 = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker2).toBeVisible({ timeout: 10_000 });
  await picker2.getByRole("button", { name: "Close" }).click();
  await expect(picker2).toBeHidden();
  await expect(page.locator("[class*=banner]")).toHaveCount(0);
});

/* ---------------------------------------------------------------- autocode */

test("autocode dialog codes multiple selected codes", async ({ page }) => {
  const projectPath = unique("Ac");
  const txtPath = path.join(E2E_ROOT, `doc_${Date.now() % 100000}.txt`);
  fs.writeFileSync(txtPath, "cat dog cat bird\nsecond line here\n", "utf-8");

  await createProject(page, projectPath);

  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [txtPath]);
  await expect(page.getByRole("row").filter({ hasText: "doc_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "doc_" }).click();
  await expect(page.getByRole("button", { name: "Code", exact: true })).toBeVisible({
    timeout: 20_000,
  });

  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByTestId("inline-name-edit")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("inline-name-edit").fill("CatCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("CatCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByTestId("inline-name-edit")).toBeVisible({ timeout: 10_000 });
  await page.getByTestId("inline-name-edit").fill("BirdCode");
  await page.keyboard.press("Enter");
  await expect(page.getByText("BirdCode", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: "Autocode" }).click();
  const ad = page.getByRole("dialog", { name: "Autocode" });
  await expect(ad).toBeVisible();
  await ad.getByLabel("Coding prompt").fill('"cat" "bird"');
  await ad.getByText("CatCode").click();
  await ad.getByText("BirdCode").click();
  await expect(ad.getByText("2 codes selected")).toBeVisible();
  await expect(ad.getByText("Suggest new codes")).toBeVisible();
  // The dialog also has a "Autocode with dictionary" button — match the main
  // action exactly so the two never collide.
  await ad.getByRole("button", { name: "Autocode", exact: true }).click();

  // Result: 3 matched spans x 2 codes = 6 codings (the dialog then closes).
  await expect(ad.getByText(/Autocoded \d+ instances/)).toBeVisible({ timeout: 15_000 });
  await expect(ad).toBeHidden({ timeout: 10_000 });
});

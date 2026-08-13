/**
 * E2E coverage for the roadmap-wave features (v0.2.0):
 *  - code promote/demote via the sidebar context menu (Word-list style)
 *  - the analyze registry listing the new reports (dictionary / stats /
 *    summary table / sentiment / doc-compare)
 *  - QTT ribbon nav + worksheet creation + note entry
 *  - the creative scratchpad panel + add note
 *  - value labels: an attribute type with a label map renders a select in
 *    the case properties editor
 *
 * Each test uses its own throwaway project (same pattern as
 * coding-flows.spec.ts); nothing here needs AI or whisper.
 */
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-roadmap");
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

/** Create a code via the sidebar "Code" button + inline name editor. */
async function createCode(page: import("@playwright/test").Page, name: string) {
  await page.getByRole("button", { name: "Code", exact: true }).click();
  const input = page.getByTestId("inline-name-edit");
  await expect(input).toBeVisible({ timeout: 10_000 });
  await input.fill(name);
  await input.press("Enter");
  await expect(page.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 10_000 });
}

/** Right-click a code row and return the sidebar context menu. */
async function openCodeMenu(page: import("@playwright/test").Page, codeName: string) {
  await page.getByRole("button", { name: codeName, exact: true }).click({ button: "right" });
  const menu = page.getByRole("menu", { name: "Context menu" });
  await expect(menu).toBeVisible({ timeout: 10_000 });
  return menu;
}

/* ---------------------------------------------------------------- promote */

test("promote/demote moves codes in the hierarchy via the context menu", async ({ page }) => {
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  const txtPath = path.join(E2E_ROOT, `prom_${Date.now() % 100000}.txt`);
  fs.writeFileSync(txtPath, "some content for the coder\n", "utf-8");

  await createProject(page, unique("Pr"));
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [txtPath]);
  await expect(page.getByRole("row").filter({ hasText: "prom_" })).toBeVisible({
    timeout: 20_000,
  });
  await page.getByRole("row").filter({ hasText: "prom_" }).click();
  await expect(page.getByRole("button", { name: "Code", exact: true })).toBeVisible({
    timeout: 20_000,
  });

  await createCode(page, "Alpha");
  await createCode(page, "Beta");

  // Demote Beta → it becomes a sub-code of the previous sibling (Alpha).
  // demoteItem refreshes the tree AFTER the demote response lands, so wait
  // for both the POST and the follow-up code-tree reload before inspecting
  // the sidebar again.
  let menu = await openCodeMenu(page, "Beta");
  const demoted = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/codes\/\d+\/demote$/.test(new URL(r.url()).pathname),
  );
  const treeReloaded = page.waitForResponse(
    (r) => r.request().method() === "GET" && new URL(r.url()).pathname === "/api/v1/codes",
  );
  await menu.getByRole("menuitem", { name: "Demote" }).click();
  await demoted;
  await treeReloaded;
  await expect(menu).toBeHidden({ timeout: 10_000 });

  // A sub-code's context menu offers "Detach from parent code".
  menu = await openCodeMenu(page, "Beta");
  await expect(menu.getByRole("menuitem", { name: "Detach from parent code" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();

  // Promote Beta → back to the top level, the detach entry disappears.
  menu = await openCodeMenu(page, "Beta");
  const promoted = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/codes\/\d+\/promote$/.test(new URL(r.url()).pathname),
  );
  const treeReloadedAgain = page.waitForResponse(
    (r) => r.request().method() === "GET" && new URL(r.url()).pathname === "/api/v1/codes",
  );
  await menu.getByRole("menuitem", { name: "Promote" }).click();
  await promoted;
  await treeReloadedAgain;
  await expect(menu).toBeHidden({ timeout: 10_000 });
  menu = await openCodeMenu(page, "Beta");
  await expect(menu.getByRole("menuitem", { name: "Detach from parent code" })).toHaveCount(0);
  await page.keyboard.press("Escape");
});

/* ------------------------------------------------------------ report list */

test("reports registry lists the roadmap reports and navigates to them", async ({ page }) => {
  await createProject(page, unique("Rg"));

  await page.getByRole("button", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Analysis" }).first()).toBeVisible();

  // The new analysis entries are registered in the left bar.
  for (const title of ["Dictionary", "Statistics", "Summary table", "Sentiment analysis", "Document comparison"]) {
    await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible({
      timeout: 10_000,
    });
  }

  // Selecting an entry marks it current and renders the report view.
  const dict = page.getByRole("button", { name: "Dictionary", exact: true });
  await dict.click();
  await expect(dict).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "Create dictionary" })).toBeVisible({
    timeout: 15_000,
  });

  const stats = page.getByRole("button", { name: "Statistics", exact: true });
  await stats.click();
  await expect(stats).toHaveAttribute("aria-current", "page");

  const compare = page.getByRole("button", { name: "Document comparison", exact: true });
  await compare.click();
  await expect(compare).toHaveAttribute("aria-current", "page");
});

/* -------------------------------------------------------------------- qtt */

test("QTT ribbon nav, worksheet creation and note entry", async ({ page }) => {
  await createProject(page, unique("Qt"));

  await page.getByRole("button", { name: "QTT", exact: true }).click();
  await expect(page.getByText("No worksheets yet. Add one to collect insights.")).toBeVisible({
    timeout: 10_000,
  });

  // Create a qualitative worksheet.
  await page.getByRole("button", { name: "Add", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "New worksheet" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Worksheet name…").fill("RQ Sheet");
  await dialog.getByRole("button", { name: "Create", exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 10_000 });

  // The sheet appears in the left bar; selecting it shows the info editors.
  await page.getByRole("button", { name: "RQ Sheet" }).click();
  await expect(page.getByText("Worksheet info", { exact: true })).toBeVisible({ timeout: 10_000 });
  const rq = page.getByLabel("Research question");
  await expect(rq).toBeVisible();
  await rq.fill("What drives the outcome?");
  await expect(rq).toHaveValue("What drives the outcome?");

  // The qualitative template has a single "Insights" section — add a note.
  // (Both the worksheet list header and the section card have an "Add"
  // button — scope to the section card's input row.)
  await expect(page.getByText("Insights", { exact: true }).first()).toBeVisible();
  const noteRow = page.getByLabel("New note…").locator("..");
  await page.getByLabel("New note…").fill("First insight from the data");
  await noteRow.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("First insight from the data")).toBeVisible({ timeout: 10_000 });
});

/* ---------------------------------------------------------------- creative */

test("creative panel opens from the ribbon and adds a note", async ({ page }) => {
  await createProject(page, unique("Cr"));

  await page.getByRole("button", { name: "Creative" }).click();
  await expect(page.getByRole("heading", { name: "Creative" }).first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("No ideas yet. Jot down a thought, quote or fragment below.")).toBeVisible();

  await page.getByLabel("Add an idea, quote or fragment…").fill("A spark of an idea");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("A spark of an idea")).toBeVisible({ timeout: 10_000 });
});

/* ---------------------------------------------------------- value labels */

test("attribute type with value labels renders a select in the case properties", async ({
  page,
}) => {
  await createProject(page, unique("Vl"));

  // Create a case via the Cases view.
  await page.getByRole("button", { name: "Cases" }).click();
  await expect(page.getByRole("heading", { name: "Cases" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Add", exact: true }).first().click();
  const caseInput = page.getByTestId("inline-name-edit");
  await expect(caseInput).toBeVisible({ timeout: 15_000 });
  await caseInput.fill("MoodCase");
  await caseInput.press("Enter");
  await expect(page.getByText("MoodCase").first()).toBeVisible({ timeout: 15_000 });
  await page.getByText("MoodCase").first().click();
  await expect(page.getByText("Properties", { exact: true }).first()).toBeVisible({
    timeout: 15_000,
  });

  // Seed an attribute TYPE with a value-label map through the API (the UI
  // has no label-edit UI yet; the backend accepts them on /attributes/types).
  const created = await page.request.post("http://localhost:8765/api/v1/attributes/types", {
    data: {
      name: "Mood",
      case_or_file: "case",
      value_type: "text",
      value_labels: { happy: "Happy", sad: "Sad" },
    },
  });
  expect(created.ok()).toBeTruthy();

  // Re-enter the case so the properties editor reloads the type list.
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.getByRole("button", { name: "Cases" }).click();
  await page.getByText("MoodCase").first().click();

  // The labelled type renders as a dropdown (label + raw value) instead of
  // a free-text input. (Exact label: "Mood" also prefixes the row's rename/
  // delete buttons and the custom-value input.)
  const mood = page.getByLabel("Mood", { exact: true });
  await expect(mood).toBeVisible({ timeout: 15_000 });
  await expect(mood.locator("option")).toContainText(["Happy (happy)", "Sad (sad)"]);

  // Choosing a value persists it through the API.
  await mood.selectOption("happy");
  await expect
    .poll(async () => {
      const res = await page.request.get("http://localhost:8765/api/v1/attributes/values");
      const values = (await res.json()) as { name: string; value: string }[];
      return values.find((v) => v.name === "Mood")?.value ?? "";
    }, { timeout: 10_000 })
    .toBe("happy");
});

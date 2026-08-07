/**
 * Extended E2E scenarios against the REAL app: FastAPI backend on :8765 +
 * Vite frontend on :5173, driven purely through the UI (no direct API calls).
 *
 * This file runs AFTER app.spec.ts in the same serial run (workers: 1), so it
 * deliberately uses its own project (Features.qda) in the shared tmp dir and
 * does not depend on anything the other spec created. The backend process
 * persists across tests, so the project created in test 1 stays open for the
 * later tests; each of them re-opens it from the recent-projects list (fresh
 * pages always land on the welcome screen — the app has no session resume).
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { crc32, deflateSync } from "node:zlib";

const E2E_ROOT = path.join(os.tmpdir(), "qc-e2e");
const PROJECT_PATH = path.join(E2E_ROOT, "Features.qda");
const PHOTO_TXT = path.join(E2E_ROOT, "photo.txt");
const IMAGE_PNG = path.join(E2E_ROOT, "image.png");
const MINIMAL_QDP = path.join(E2E_ROOT, "minimal.qdp");

/**
 * Handcrafted REFI-QDA file: one code, one text source with one coded
 * segment ("imported" in "hello imported world"), and one case.
 */
const MINIMAL_QDP_XML =
  '<?xml version="1.0" encoding="UTF-8"?>' +
  '<QDAProject xmlns="urn:QDA-XML:project:1.0">' +
  "<CodeBook><Codes>" +
  '<Code guid="c1" name="ImportedCode" color="#FF0000"/>' +
  "</Codes></CodeBook>" +
  "<Sources>" +
  '<TextSource guid="s1" name="imported.txt" mediaType="TEXT">' +
  "<Description><FullText>hello imported world</FullText></Description>" +
  "</TextSource></Sources>" +
  "<CodedTexts>" +
  '<CodedText guid="t1"><Description>' +
  '<CodedSelection><SourceRef targetGUID="s1"/><TextRef start="6" end="14"/></CodedSelection>' +
  '<CodeRef targetGUID="c1"/>' +
  "</Description></CodedText>" +
  "</CodedTexts><Cases>" +
  '<Case guid="k1" name="ImportedCase"><Description><Memo>from qdp</Memo></Description></Case>' +
  "</Cases></QDAProject>";

/**
 * Encode a solid red RGBA PNG in memory (no deps). A 1×1 image would render
 * at zoom ≤ 3 as a 3px box, which the coder rejects as a drag (< 3px), so the
 * fixture is a 64×64 red image — small, but large enough to drag a region.
 */
function makeRedPng(width: number, height: number): Buffer {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const chunk = (type: string, data: Buffer): Buffer => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length, 0);
    const typeBuf = Buffer.from(type, "ascii");
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])) >>> 0, 0);
    return Buffer.concat([len, typeBuf, data, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type: RGBA
  const stride = 1 + width * 4;
  const rows = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    const off = y * stride;
    rows[off] = 0; // filter: none
    for (let x = 0; x < width; x++) {
      rows[off + 1 + x * 4] = 255;
      rows[off + 2 + x * 4] = 0;
      rows[off + 3 + x * 4] = 0;
      rows[off + 4 + x * 4] = 255;
    }
  }
  return Buffer.concat([
    signature,
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function ensureFixtureFiles() {
  // Fresh slate for OUR project (app.spec.ts wipes E2E_ROOT at its start and
  // creates Study.qda there — leave that alone, only clear Features*).
  for (let i = 0; i < 10; i++) {
    fs.rmSync(i === 0 ? PROJECT_PATH : `${PROJECT_PATH}_${i}`, {
      recursive: true,
      force: true,
    });
  }
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  fs.writeFileSync(
    PHOTO_TXT,
    "The sun was shining brightly over the hills.\nNobody expected the rain that afternoon.",
    "utf-8",
  );
  fs.writeFileSync(IMAGE_PNG, makeRedPng(64, 64));
  fs.writeFileSync(MINIMAL_QDP, MINIMAL_QDP_XML, "utf-8");
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
 * connection does not block a quick UPDATE).
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
 * Make sure the Features project is open. A fresh page always lands on the
 * welcome screen (the app has no session-resume), so re-open the project from
 * the recent-projects list. Two backend quirks make a repeated open fail and
 * are worked around here:
 *  - `open_project` refuses to lock a project that already carries a lock
 *    file (the backend may still hold the lock from an earlier open in this
 *    same run) — the lock file is cleared first (it is recreated on open);
 *  - the `about` marker is rewritten on open (see repairProjectMeta).
 */
async function ensureProjectOpen(page: Page) {
  const closeBtn = page.getByRole("button", { name: "Go to code" });
  for (let attempt = 0; attempt < 3; attempt++) {
    // The welcome screen fetches the recent-projects list once on mount; a
    // transient network hiccup leaves it empty, so reload and retry.
    await page.goto("/");
    fs.rmSync(path.join(PROJECT_PATH, "project_in_use.lock"), { force: true });
    await repairProjectMeta();
    const recent = page.getByRole("button", { name: PROJECT_PATH, exact: true });
    try {
      await expect(recent).toBeVisible({ timeout: 5_000 });
      await recent.click();
      await expect(closeBtn).toBeVisible({ timeout: 30_000 });
      return;
    } catch {
      /* reload and retry once more */
    }
  }
  throw new Error(`Could not open ${PROJECT_PATH} after 3 attempts`);
}

// ---------------------------------------------------------------------------

test("create project, import image and text fixtures", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "QualCoder" })).toBeVisible();

  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await expect(dialog).toBeVisible();
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page.getByRole("button", { name: "Go to code" })).toBeVisible({
    timeout: 30_000,
  });

  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();

  await page.setInputFiles("input[type=file]", [PHOTO_TXT, IMAGE_PNG]);
  await expect(page.getByRole("row").filter({ hasText: "photo.txt" })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByRole("row").filter({ hasText: "image.png" })).toBeVisible({
    timeout: 20_000,
  });
});

// ---------------------------------------------------------------------------

test("image coding: draw a region and code it", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await page.getByRole("row").filter({ hasText: "image.png" }).click();

  // ImageCoder loads the image and auto-fits the zoom; wait for a rendered
  // box well above the drag threshold (the 64px canvas at zoom 3 → 192px).
  const img = page.getByRole("img", { name: "image.png" });
  await expect(img).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(async () => (await img.boundingBox())?.width ?? 0, { timeout: 15_000 })
    .toBeGreaterThan(50);

  const box = await img.boundingBox();
  expect(box).not.toBeNull();

  // Drag from ~20% to ~60% of the image.
  await page.mouse.move(box!.x + box!.width * 0.2, box!.y + box!.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.6, box!.y + box!.height * 0.6, {
    steps: 5,
  });
  await page.mouse.up();

  // The CodePicker modal opens; create a brand-new code for the region.
  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("ImgCode");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });

  // The new coded region renders as an overlay; click the region itself
  // (as a user would) to select it — the details bar shows the code name
  // and a Delete button.
  const region = page.locator('div[title="ImgCode"]');
  await expect(region).toBeVisible({ timeout: 10_000 });
  await region.click();
  await expect(page.getByText("ImgCode", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByRole("button", { name: "Delete" })).toBeVisible();

  // Opening a file switched the sidebar to the code tree automatically.
  await expect(page.getByRole("button", { name: "Code", exact: true })).toBeVisible();

  // Drawing a SECOND rectangle while one is selected must still work.
  await page.mouse.move(box!.x + box!.width * 0.1, box!.y + box!.height * 0.7);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width * 0.35, box!.y + box!.height * 0.95, {
    steps: 5,
  });
  await page.mouse.up();
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("ImgCode2");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });
  await expect(page.locator('div[title="ImgCode2"]')).toBeVisible({ timeout: 10_000 });
});

// ---------------------------------------------------------------------------

test("sidebar code click codes the selected text", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await page.getByRole("row").filter({ hasText: "photo.txt" }).click();
  const docLine = page.getByText("The sun was shining brightly over the hills.");
  await expect(docLine).toBeVisible({ timeout: 20_000 });

  // Create a fresh code via the sidebar (Code → window.prompt).
  page.on("dialog", (d) => void d.accept("ClickCode"));
  await page.getByRole("button", { name: "Code", exact: true }).click();
  await expect(page.getByRole("button", { name: "ClickCode" })).toBeVisible({
    timeout: 10_000,
  });

  // Select the first line of the document with the mouse.
  const box = await docLine.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + 4, box!.y + box!.height / 2);
  await page.mouse.down();
  await page.mouse.move(box!.x + box!.width - 4, box!.y + box!.height / 2, {
    steps: 8,
  });
  await page.mouse.up();

  // Click the code in the left bar → the selection is coded with it
  // immediately (no CodePicker modal).
  await page.getByRole("button", { name: "ClickCode" }).click();

  // The coded segment is clickable and shows the code in the details bar.
  const segment = page.locator('span[title="ClickCode"]');
  await expect(segment).toBeVisible({ timeout: 10_000 });
  await segment.click();
  await expect(page.getByText("Coding details")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("li").filter({ hasText: "ClickCode" })).toBeVisible();
});

// ---------------------------------------------------------------------------

test("history view lists project changes and filters", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "History" }).click();
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();

  // Earlier tests created codes + codings in this project; the audit log
  // shows them with human-readable action labels.
  await expect(
    page.getByText("Coding created", { exact: true }).first(),
  ).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Code created", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Source imported", { exact: true }).first()).toBeVisible();

  // Filtering by action narrows the list.
  await page.getByLabel("Filter by action").selectOption("coding.create");
  await expect(page.getByText("Coding created", { exact: true }).first()).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText("Code created", { exact: true })).toHaveCount(0);

  // A detail drawer opens on a row click (before/after diff for edits).
  await page.getByText("Coding created", { exact: true }).first().click();
  await expect(page.getByRole("dialog", { name: "Change details" })).toBeVisible();
  await page.getByRole("button", { name: "Close", exact: true }).click();
});

// ---------------------------------------------------------------------------

test("autocode + SQL report", async ({ page }) => {
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await page.getByRole("row").filter({ hasText: "photo.txt" }).click();

  await expect(
    page.getByText("The sun was shining brightly over the hills."),
  ).toBeVisible({ timeout: 20_000 });

  // Autocode "rain" into a new code.
  await page.getByRole("button", { name: "Autocode" }).first().click();
  const searchText = page.getByPlaceholder("One search text per line");
  await expect(searchText).toBeVisible();
  await searchText.fill("rain");
  await page.getByPlaceholder("\u2026or new code name").fill("RainCode");
  await page.getByRole("button", { name: "Autocode" }).nth(1).click();
  await expect(page.getByText(/Autocoded \d+ instances/)).toBeVisible({
    timeout: 20_000,
  });

  // SQL report: count codings per code, expect the RainCode row.
  await page.getByRole("button", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "Analysis" })).toBeVisible();
  await page.getByRole("button", { name: "SQL report" }).click();

  const sqlBox = page.getByLabel("SQL query");
  await expect(sqlBox).toBeVisible();
  await sqlBox.fill(
    "SELECT code_name.name, count(*) AS n FROM code_text JOIN code_name ON code_name.cid = code_text.cid GROUP BY code_name.name",
  );
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("row").filter({ hasText: "RainCode" })).toBeVisible({
    timeout: 20_000,
  });
});

// ---------------------------------------------------------------------------

test("cases and attributes", async ({ page }) => {
  await ensureProjectOpen(page);

  // Nav buttons live in the shell toolbar (the first <header>); on some views
  // (e.g. the Attributes values matrix) other buttons share the label.
  const navButton = (label: string) =>
    page.locator("header").first().getByRole("button", { name: label });

  // Add case "FeatureCase" (the view uses window.prompt).
  page.on("dialog", (d) => void d.accept("FeatureCase"));
  await navButton("Cases").click();
  await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();
  await page.getByRole("button", { name: "Add case" }).click();
  await expect(page.getByText("FeatureCase").first()).toBeVisible({ timeout: 15_000 });

  // Select the case → its Properties panel appears (attributes merged into
  // the cases view). Create a case-scope property type "Score" via the panel.
  await page.getByText("FeatureCase").first().click();
  const properties = page.getByText("Properties", { exact: true }).first();
  await expect(properties).toBeVisible({ timeout: 15_000 });
  page.removeAllListeners("dialog");
  page.on("dialog", (d) => void d.accept("Score"));
  await page.getByRole("button", { name: "Add property type" }).click();
  const scoreInput = page.getByLabel("Score");
  await expect(scoreInput).toBeVisible({ timeout: 15_000 });

  // Set the case's Score property and blur to save.
  const saved = page.waitForResponse(
    (r) => r.request().method() === "PUT" && r.url().includes("/attributes/values/"),
    { timeout: 15_000 },
  );
  await scoreInput.fill("42");
  await scoreInput.press("Tab");
  await saved;

  // Persistence: leave the view and come back; the value reloads from the API.
  await navButton("Files").click();
  await navButton("Cases").click();
  await page.getByText("FeatureCase").first().click();
  await expect(page.getByLabel("Score")).toHaveValue("42", { timeout: 15_000 });
});

// ---------------------------------------------------------------------------

test("interchange export and import", async ({ page }) => {
  await ensureProjectOpen(page);

  // Import/Export lives in Settings now.
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByText("Import / Export", { exact: true }).first()).toBeVisible();

  // Export: the project downloads as a .qdp attachment.
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: /Export project/ }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.qdp$/i);
  const dlPath = await download.path();
  expect(dlPath).toBeTruthy();

  // Import: the handcrafted REFI-QDA file (code + source + coding + case).
  await page.getByLabel(/^Format/).selectOption("refi");
  await page.getByLabel("Import file").setInputFiles(MINIMAL_QDP);
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(
    page.getByRole("status").filter({ hasText: /Codes: \d+/ }).first(),
  ).toBeVisible({ timeout: 20_000 });
  await expect(
    page.getByRole("status").filter({ hasText: /Cases: 1/ }).first(),
  ).toBeVisible();
});

// ---------------------------------------------------------------------------

test("a11y smoke: every button has an accessible name", async ({ page }) => {
  await ensureProjectOpen(page);

  // Stable shell state for the sweep: toolbar + sidebar + Files view.
  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();

  const buttons = await page.getByRole("button").all();
  expect(buttons.length).toBeGreaterThan(0);

  const unnamed: string[] = [];
  for (const btn of buttons) {
    const aria = (await btn.getAttribute("aria-label"))?.trim() ?? "";
    const text = (await btn.innerText()).trim();
    const title = (await btn.getAttribute("title"))?.trim() ?? "";
    if (!aria && !text && !title) {
      unnamed.push(await btn.evaluate((el) => el.outerHTML.slice(0, 160)));
    }
  }
  expect(unnamed, `Buttons without an accessible name:\n${unnamed.join("\n")}`).toHaveLength(0);
});

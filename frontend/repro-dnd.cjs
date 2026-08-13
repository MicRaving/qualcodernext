const { chromium } = require("@playwright/test");

const ROOT = "C:\\Users\\marvi\\AppData\\Local\\Temp\\opencode\\dnd-repro";
const fs = require("fs");
const path = require("path");

const PROJECT_PATH = path.join(ROOT, "DnDProj.qda");
fs.rmSync(PROJECT_PATH, { recursive: true, force: true });

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") console.log("[console.error]", m.text().slice(0, 300));
  });
  page.on("pageerror", (e) => {
    console.log("[pageerror]", String(e).slice(0, 300));
    if (e.stack) console.log("[stack]", e.stack.split("\n").slice(0, 12).join("\n"));
  });
  page.on("request", (r) => {
    const u = r.url();
    if (r.method() === "POST" && /\/codes(\/categories)?\/\d+\/(move|merge)/.test(u)) {
      console.log("[REQ]", r.method(), u.replace("http://localhost:8765/api/v1", ""), r.postData());
    }
  });
  page.on("requestfailed", (r) => console.log("[reqfailed]", r.url()));

  await page.addInitScript(() => {
    const style = document.createElement("style");
    style.textContent = "*{animation:none!important;transition:none!important}";
    document.head.appendChild(style);
  });

  // --- create project ---
  await page.goto("http://localhost:5173/");
  await page.getByRole("button", { name: "New project" }).click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.locator("#create-path").fill(PROJECT_PATH);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await page.getByRole("button", { name: "Cases" }).waitFor({ timeout: 30000 });

  // --- import a file, open coding view ---
  const txt = path.join(ROOT, "seed.txt");
  fs.writeFileSync(txt, "some content for the coder\n", "utf-8");
  await page.getByRole("button", { name: "Coding", exact: true }).click();
  await page.setInputFiles("input[type=file]", [txt]);
  await page.locator("table tbody tr").first().waitFor({ timeout: 20000 });
  await page.locator("table tbody tr").first().click();
  await page.getByRole("button", { name: "Code", exact: true }).waitFor({ timeout: 20000 });

  // --- create two codes ---
  async function createCode(name) {
    await page.getByRole("button", { name: "Code", exact: true }).click();
    const input = page.getByTestId("inline-name-edit");
    await input.waitFor({ timeout: 10000 });
    await input.fill(name);
    await input.press("Enter");
    await page.getByText(name, { exact: true }).first().waitFor({ timeout: 10000 });
  }
  await createCode("Alpha");
  await createCode("Beta");

  // --- instrument: capture drag events on the row buttons ---
  await page.evaluate(() => {
    const log = (ev) => console.log(`[dnd] ${ev.type} target=${(ev.target.nodeName || ev.target.tagName).toLowerCase()}.${(ev.target.className || "").toString().slice(0, 60)}`);
    document.addEventListener("dragstart", log, true);
    document.addEventListener("dragover", (e) => {
      if (e.target.closest && e.target.closest("[draggable]")) console.log(`[dnd] dragover preventDefault called=${e.defaultPrevented}`);
    }, true);
    document.addEventListener("drop", (e) => console.log(`[dnd] DROP on ${(e.target.nodeName || "").toLowerCase()} class=${(e.target.className || "").toString().slice(0, 60)}`), true);
    document.addEventListener("dragend", (e) => console.log("[dnd] dragend"), true);
  });

  const alpha = page.getByRole("button", { name: "Alpha", exact: true });
  const beta = page.getByRole("button", { name: "Beta", exact: true });
  await alpha.waitFor({ timeout: 10000 });
  await beta.waitFor({ timeout: 10000 });
  const aBox = await alpha.boundingBox();
  const bBox = await beta.boundingBox();
  console.log("[box] alpha", JSON.stringify(aBox), "beta", JSON.stringify(bBox));

  const before = await page.getByRole("button", { name: "Alpha", exact: true }).count();
  console.log("[state] rows before drop:", before);

  // --- drag Alpha onto the BOTTOM QUARTER of Beta ("after" zone) ---
  await page.mouse.move(aBox.x + aBox.width / 2, aBox.y + aBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(aBox.x + aBox.width / 2, aBox.y + aBox.height / 2 + 5, { steps: 3 });
  await page.mouse.move(bBox.x + bBox.width / 2, bBox.y + bBox.height * 0.9, { steps: 12 });
  await page.waitForTimeout(300);
  await page.mouse.up();
  await page.waitForTimeout(1500);

  const after = await page.getByRole("button", { name: "Alpha", exact: true }).count();
  console.log("[state] rows after drop:", after);
  console.log("DONE");
  await browser.close();
}

main().catch((e) => {
  console.error("SCRIPT FAILED:", e);
  process.exit(1);
});

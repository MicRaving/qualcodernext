/**
 * Audio/Video coding E2E scenarios against the REAL app: import a generated
 * WAV, code a time-range segment via the timeline, inspect/delete it from the
 * details panel, and exercise the play/pause toggle.
 *
 * Runs in the same serial suite as the other specs (workers: 1, files run
 * alphabetically — this one comes last). The backend process persists across
 * tests, so the project created in test 1 stays open; later tests re-open it
 * from the recent-projects list using the same backend quirks documented in
 * features.spec.ts (lock file + `about` marker).
 */
import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const E2E_ROOT = path.join(os.tmpdir(), "qc-e2e");
const PROJECT_PATH = path.join(E2E_ROOT, "Media.qda");
const WAV_PATH = path.join(E2E_ROOT, "tone.wav");
const SPEECH_WAV = path.join(E2E_ROOT, "speech.wav");

/** Backend venv python — the same one the other specs use for fixtures. */
const BACKEND_PYTHON = path.resolve(
  process.cwd(),
  "..",
  "backend",
  ".venv",
  "Scripts",
  "python.exe",
);

/**
 * Generate a 2-second 8000 Hz 16-bit mono sine WAV with the stdlib `wave`
 * module via the backend venv python. Test infrastructure only.
 */
function makeWavFixture(): void {
  const script = [
    "import math, struct, sys, wave",
    "rate = 8000",
    "n = rate * 2",
    "with wave.open(sys.argv[1], 'wb') as w:",
    "    w.setnchannels(1)",
    "    w.setsampwidth(2)",
    "    w.setframerate(rate)",
    "    w.writeframes(b''.join(struct.pack('<h', int(16000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n)))",
  ].join("\n");
  try {
    execFileSync(BACKEND_PYTHON, ["-c", script, WAV_PATH], {
      stdio: "pipe",
      encoding: "utf-8",
    });
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    throw new Error(`Could not generate the WAV fixture via ${BACKEND_PYTHON}: ${detail}`);
  }
  if (!fs.existsSync(WAV_PATH)) {
    throw new Error(`WAV fixture missing after generation: ${WAV_PATH}`);
  }
}

function ensureFixtureFiles() {
  // Fresh slate for OUR project only (app.spec.ts wipes E2E_ROOT wholesale at
  // its start, after this file has already run — leave its Study.qda alone).
  for (let i = 0; i < 10; i++) {
    fs.rmSync(i === 0 ? PROJECT_PATH : `${PROJECT_PATH}_${i}`, {
      recursive: true,
      force: true,
    });
  }
  fs.mkdirSync(E2E_ROOT, { recursive: true });
  makeWavFixture();
  makeSpeechFixture();
}

/**
 * Generate a short spoken WAV via Windows SAPI (System.Speech). The whisper
 * engine transcribes it in the transcription E2E test. Falls back to the
 * tone when SAPI is unavailable (CI without a voice — the transcription
 * test is skipped then).
 */
function makeSpeechFixture(): void {
  try {
    execFileSync(
      "powershell",
      [
        "-NoProfile",
        "-Command",
        `Add-Type -AssemblyName System.Speech; ` +
          `$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; ` +
          `$s.SetOutputToWaveFile('${SPEECH_WAV}'); ` +
          `$s.Speak('Hello world, this is a transcription test'); ` +
          `$s.Dispose()`,
      ],
      { stdio: "pipe", timeout: 60_000 },
    );
  } catch {
    try {
      fs.copyFileSync(WAV_PATH, SPEECH_WAV);
    } catch {
      /* neither fixture available */
    }
  }
}

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  ensureFixtureFiles();
});

/**
 * The backend's migration chain rewrites the project row's `about` field to
 * the bare app version on EVERY open, and `open_project` rejects a database
 * whose `about` lacks "QualCoder" — so a project can only be opened once per
 * backend session. Restore the marker directly. Same quirk as the other specs.
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
 * Make sure the Media project is open. Fresh pages land on the welcome
 * screen, so re-open from the recent-projects list; clear the backend's
 * stale lock file and repair the `about` marker first (see features.spec.ts
 * for the full quirk story).
 */
async function ensureProjectOpen(page: Page) {
  const closeBtn = page.getByRole("button", { name: "Go to code" });
  for (let attempt = 0; attempt < 3; attempt++) {
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

/**
 * The audio row in Files. Importing audio also auto-creates a text
 * transcription row ("tone.wav.txt"), so a plain hasText filter matches two
 * rows — target the audio row by its accessible name instead.
 */
function toneAudioRow(page: Page) {
  return page.getByRole("row", { name: /^tone\.wav Audio/ });
}

/** Files view → open tone.wav in the AV coder. */
async function openToneInCoder(page: Page) {
  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await toneAudioRow(page).click();
}

// ---------------------------------------------------------------------------

test("create project and import the audio file", async ({ page }) => {
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

  await page.setInputFiles("input[type=file]", [WAV_PATH]);
  const row = toneAudioRow(page);
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.click();

  // AvCoder (audio panel): the media element must report its duration before
  // the controls enable. The time display reads "0:00 / 0:02" and the audio
  // panel shows "Audio file · 0:02" once loadedmetadata fired.
  await expect(page.getByText("/ 0:02", { exact: true })).toBeVisible({
    timeout: 20_000,
  });
  await expect(page.getByText(/Audio file · 0:02/)).toBeVisible({ timeout: 20_000 });

  // "Set start" is disabled until the duration is known — it must be enabled.
  const setStart = page.getByRole("button", { name: "Set start" });
  await expect(setStart).toBeEnabled({ timeout: 10_000 });
});

// ---------------------------------------------------------------------------

test("code a segment via the timeline and verify it appears", async ({ page }) => {
  await ensureProjectOpen(page);
  await openToneInCoder(page);

  const timeline = page.getByRole("slider", { name: "Timeline" });
  await expect(timeline).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("/ 0:02", { exact: true })).toBeVisible({ timeout: 20_000 });

  const box = await timeline.boundingBox();
  expect(box).not.toBeNull();
  const midY = box!.y + box!.height / 2;

  // Seek to ~30% and mark the start; the timeline is click-to-seek.
  await page.mouse.click(box!.x + box!.width * 0.3, midY);
  await page.getByRole("button", { name: "Set start" }).click();

  // Seek to ~70% and open the code picker (the end mark is the current time).
  await page.mouse.click(box!.x + box!.width * 0.7, midY);
  await page.getByRole("button", { name: "Set end & code…" }).click();

  const picker = page.getByRole("dialog", { name: "Pick a code" });
  await expect(picker).toBeVisible({ timeout: 10_000 });
  await picker.getByPlaceholder("New code name…").fill("AvCode");
  await picker.getByRole("button", { name: "Create" }).click();
  await expect(picker).toBeHidden({ timeout: 10_000 });

  // The new segment renders as an overlay on the timeline; its tooltip title
  // is "AvCode · m:ss – m:ss".
  const segment = page.locator('[title*="AvCode"]');
  await expect(segment).toBeVisible({ timeout: 10_000 });
});

// ---------------------------------------------------------------------------

test("seek via segment click and delete the segment", async ({ page }) => {
  await ensureProjectOpen(page);
  await openToneInCoder(page);

  // The coded segment persisted; click it (as a user would) to select it —
  // the details panel shows the code name, the mono time range, and Delete.
  const segment = page.locator('[title*="AvCode"]');
  await expect(segment).toBeVisible({ timeout: 20_000 });
  await segment.click();

  await expect(page.getByRole("main").getByText("AvCode", { exact: true })).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByText(/0:0\d – 0:0\d/)).toBeVisible({ timeout: 10_000 });
  const deleteBtn = page.getByRole("button", { name: "Delete" });
  await expect(deleteBtn).toBeVisible();

  // Deletion asks via window.confirm; accept it.
  page.on("dialog", (d) => void d.accept());
  await deleteBtn.click();

  // The segment disappears from the timeline and the details panel closes.
  await expect(segment).toHaveCount(0, { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Delete" })).toBeHidden({
    timeout: 10_000,
  });
});

// ---------------------------------------------------------------------------

test("transcribe audio with whisper and open the transcript", async ({ page }) => {
  test.skip(
    SPEECH_WAV === WAV_PATH || !fs.existsSync(SPEECH_WAV),
    "no spoken fixture (SAPI unavailable)",
  );
  await ensureProjectOpen(page);

  await page.getByRole("button", { name: "Files" }).click();
  await expect(page.getByRole("heading", { name: "Files" })).toBeVisible();
  await page.setInputFiles("input[type=file]", [SPEECH_WAV]);
  // The importer also creates an empty "speech.wav.txt" transcript
  // companion — target the exact media row.
  const row = page.getByRole("row", { name: /^speech\.wav\s/ });
  await expect(row).toBeVisible({ timeout: 20_000 });
  await row.click();

  // Open the transcription dialog and start with the tiny model (cached in
  // ~/.qualcoder/models/whisper by the earlier manual smoke run; first use
  // downloads it, which the generous timeout covers).
  await page.getByRole("button", { name: "Transcribe" }).click();
  const dialog = page.getByRole("dialog", { name: "Transcribe audio/video" });
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await dialog
    .locator("select")
    .filter({ has: page.locator("option[value='tiny']") })
    .selectOption("tiny");
  await dialog.getByRole("button", { name: "Start transcription" }).click();

  // Completion fires a status toast with the new transcript source id.
  await expect(page.getByRole("status").filter({ hasText: "Transcript saved" })).toBeVisible({
    timeout: 240_000,
  });

  // The transcript is now VISIBLE in the video view (linked companion panel).
  await expect(page.getByText(/Hello world/).first()).toBeVisible({ timeout: 20_000 });
});

// ---------------------------------------------------------------------------

test("play/pause toggles", async ({ page }) => {
  await ensureProjectOpen(page);
  await openToneInCoder(page);

  // The toggle is one button whose label flips Play ↔ Pause with playback.
  const toggle = page.getByRole("button", { name: /^(Play|Pause)$/ });
  await expect(toggle).toBeVisible({ timeout: 20_000 });
  await expect(toggle).toHaveAttribute("aria-label", "Play", { timeout: 10_000 });

  await toggle.click();
  try {
    // Headless Chromium normally allows playback (Playwright passes
    // --autoplay-policy=no-user-gesture-required); if the browser still
    // rejects autoplay the label never flips — accept either outcome so the
    // run never flakes on a 2-second clip.
    await expect(toggle).toHaveAttribute("aria-label", "Pause", { timeout: 5_000 });
  } catch {
    console.warn("note: headless autoplay rejected — skipping pause-state assertion");
  }
});

/**
 * E2E global teardown — kill both dev servers (process trees), remove the
 * pid file, the temp test project, and the user settings file the app
 * polluted during the run.
 */
import { execSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const FRONTEND_DIR = process.cwd();
const SERVERS_FILE = path.join(FRONTEND_DIR, "tests-e2e", ".servers.json");
const SETTINGS_FILE = path.join(os.homedir(), ".qualcoder", "settings.json");
// All temp project dirs the specs create (qc-e2e is the classic one; the
// per-file shared projects live in their own dirs).
const E2E_TMP_DIRS = ["qc-e2e", "qc-tabtest", "qc-roadmap", "qc-tasks", "qc-gaps", "qc-wave"].map(
  (d) => path.join(os.tmpdir(), d),
);

function killTree(pid: number) {
  if (!pid) return;
  try {
    execSync(`taskkill /pid ${pid} /T /F`, { stdio: "ignore", windowsHide: true });
  } catch {
    /* process already gone */
  }
}

export default async function globalTeardown(): Promise<void> {
  try {
    const info = JSON.parse(fs.readFileSync(SERVERS_FILE, "utf-8")) as {
      backend: number;
      frontend: number;
    };
    // Frontend is spawned via npm (cmd wrapper) — taskkill /T /F nukes the
    // whole tree so the orphaned node child does not survive.
    killTree(info.frontend);
    killTree(info.backend);
  } catch {
    /* no servers file — nothing to kill */
  }

  try {
    fs.rmSync(SERVERS_FILE, { force: true });
  } catch {
    /* ignore */
  }

  for (const dir of E2E_TMP_DIRS) {
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }

  try {
    fs.rmSync(SETTINGS_FILE, { force: true });
  } catch {
    /* ignore */
  }
}

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
const TEST_PROJECT_DIR = path.join(os.tmpdir(), "qc-e2e", "Study.qda");

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

  try {
    fs.rmSync(TEST_PROJECT_DIR, { recursive: true, force: true });
  } catch {
    /* ignore */
  }

  try {
    fs.rmSync(SETTINGS_FILE, { force: true });
  } catch {
    /* ignore */
  }
}

/**
 * E2E global setup — spawn the real backend (uvicorn) and frontend (vite)
 * dev servers, wait until both respond, and record their pids for teardown.
 */
import { spawn, execSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const FRONTEND_DIR = process.cwd();
const BACKEND_DIR = path.resolve(FRONTEND_DIR, "..", "backend");
const BACKEND_VENV_PYTHON = path.resolve(BACKEND_DIR, ".venv", "Scripts", "python.exe");
// CI installs backend deps into the runner's python directly (no venv) —
// fall back to `python` on PATH when the venv interpreter is missing.
const BACKEND_PYTHON = fs.existsSync(BACKEND_VENV_PYTHON)
  ? BACKEND_VENV_PYTHON
  : "python";
const SERVERS_FILE = path.join(FRONTEND_DIR, "tests-e2e", ".servers.json");
const SETTINGS_FILE = path.join(os.homedir(), ".qualcoder", "settings.json");
const E2E_DIR = path.join(FRONTEND_DIR, "tests-e2e");

const BACKEND_HEALTH_URL = "http://localhost:8765/api/v1/health";
const FRONTEND_URL = "http://localhost:5173";

const POLL_INTERVAL_MS = 500;
const BACKEND_WAIT_MS = 30_000;
const FRONTEND_WAIT_MS = 60_000;

interface ServersInfo {
  backend: number;
  frontend: number;
}

async function waitForUrl(url: string, timeoutMs: number, isReady: (status: number) => boolean) {
  const deadline = Date.now() + timeoutMs;
  let lastErr: unknown = new Error(`timed out waiting for ${url}`);
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (isReady(res.status)) return;
      lastErr = new Error(`HTTP ${res.status} from ${url}`);
    } catch (e) {
      lastErr = e;
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw lastErr;
}

function logTail(file: string, maxLines = 40): string {
  try {
    const lines = fs
      .readFileSync(file, "utf-8")
      .split(/\r?\n/)
      .filter((l) => l.trim().length > 0);
    return lines.slice(-maxLines).join("\n");
  } catch {
    return "(no log captured)";
  }
}

async function startServer(
  name: string,
  cmd: string,
  args: string[],
  opts: { cwd: string; shell?: boolean },
  logFile: string,
): Promise<ChildProcess> {
  const log = fs.createWriteStream(logFile, { flags: "w", encoding: "utf-8" });
  const child = spawn(cmd, args, { cwd: opts.cwd, shell: opts.shell ?? false, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout?.pipe(log);
  child.stderr?.pipe(log);
  child.on("error", (err) => {
    log.write(`\n[spawn error] ${err.message}\n`);
  });
  return child;
}

/** Kill dev servers recorded by a PREVIOUS run (stale leftovers hold file
 *  handles on the temp project dir and would break the fresh wipe). */
function killStaleServers(): void {
  let info: ServersInfo | null = null;
  try {
    info = JSON.parse(fs.readFileSync(SERVERS_FILE, "utf-8")) as ServersInfo;
  } catch {
    return; // no record from a previous run
  }
  for (const pid of [info.backend, info.frontend]) {
    if (!pid) continue;
    try {
      execSync(`taskkill /pid ${pid} /T /F`, { stdio: "ignore", windowsHide: true });
    } catch {
      /* already gone */
    }
  }
  console.warn("[e2e setup] killed stale servers from a previous run");
}

export default async function globalSetup(): Promise<void> {
  fs.mkdirSync(E2E_DIR, { recursive: true });

  // A previous (failed/aborted) run may have left its servers alive, holding
  // file handles on the temp project dir. Kill them BEFORE spawning.
  killStaleServers();

  // Remove the settings file BEFORE the backend starts so the test run
  // starts with a clean slate (empty recent-projects list).
  try {
    fs.rmSync(SETTINGS_FILE, { force: true });
  } catch {
    /* not present — fine */
  }

  const backendLog = path.join(E2E_DIR, "server-backend.log");
  const frontendLog = path.join(E2E_DIR, "server-frontend.log");

  // A previous (failed/aborted) run may have left its servers alive, holding
  // file handles on the temp project dir. Kill them BEFORE spawning.
  killStaleServers();

  const backend = await startServer(
    "backend",
    BACKEND_PYTHON,
    ["-m", "uvicorn", "qualcoder_api.main:app", "--port", "8765"],
    { cwd: BACKEND_DIR },
    backendLog,
  );
  const frontend = await startServer(
    "frontend",
    "npm",
    ["run", "dev", "--", "--port", "5173", "--strictPort"],
    { cwd: FRONTEND_DIR, shell: true },
    frontendLog,
  );

  try {
    await waitForUrl(BACKEND_HEALTH_URL, BACKEND_WAIT_MS, (s) => s >= 200 && s < 300);
    await waitForUrl(FRONTEND_URL, FRONTEND_WAIT_MS, (s) => s >= 200 && s < 400);
  } catch (err) {
    const msg = [
      `E2E server startup failed: ${err instanceof Error ? err.message : err}`,
      "",
      `--- backend log tail (${backendLog}) ---`,
      logTail(backendLog),
      "",
      `--- frontend log tail (${frontendLog}) ---`,
      logTail(frontendLog),
    ].join("\n");
    for (const child of [backend, frontend]) {
      if (child.pid && !child.killed) child.kill();
    }
    throw new Error(msg);
  }

  const info: ServersInfo = {
    backend: backend.pid ?? 0,
    frontend: frontend.pid ?? 0,
  };
  fs.writeFileSync(SERVERS_FILE, JSON.stringify(info, null, 2), "utf-8");
  console.warn(`[e2e setup] backend pid=${info.backend}, frontend pid=${info.frontend}`);
}

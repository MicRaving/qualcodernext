/**
 * Server-session storage (SERVER_PLAN.md §6.7).
 *
 * Bearer token lives in memory + sessionStorage (tab-scoped, cleared on
 * tab close) — never localStorage, so a persisted XSS payload cannot steal
 * a long-lived token from disk. The active project id is less sensitive and
 * stays in sessionStorage too. Swapping in a Tauri secure store later only
 * touches this module. In local (desktop) mode nothing here is used.
 */
import { SERVER_MODE } from "@/lib/config";

const TOKEN_KEY = "qc-server-token";
const PROJECT_KEY = "qc-server-project";

let memoryToken: string | null = null;

function sessionGet(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function sessionSet(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    /* storage unavailable — memory copy still works until reload */
  }
}

function sessionDel(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
  // Migrate legacy localStorage entries (pre-fix clients) then drop them.
  try {
    localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function isServerMode(): boolean {
  return SERVER_MODE;
}

export function getToken(): string | null {
  if (!SERVER_MODE) return null;
  if (memoryToken) return memoryToken;
  const stored = sessionGet(TOKEN_KEY);
  if (stored) {
    memoryToken = stored;
    return stored;
  }
  // One-time migration: pick up a legacy localStorage token, move it to
  // sessionStorage, and delete the persistent copy.
  try {
    const legacy = localStorage.getItem(TOKEN_KEY);
    if (legacy) {
      memoryToken = legacy;
      sessionSet(TOKEN_KEY, legacy);
      try {
        localStorage.removeItem(TOKEN_KEY);
      } catch {
        /* ignore */
      }
      return legacy;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function setToken(token: string): void {
  memoryToken = token;
  sessionSet(TOKEN_KEY, token);
}

export function clearToken(): void {
  memoryToken = null;
  sessionDel(TOKEN_KEY);
  sessionDel(PROJECT_KEY);
}

export function getProjectId(): string | null {
  if (!SERVER_MODE) return null;
  return sessionGet(PROJECT_KEY);
}

export function setProjectId(id: string | null): void {
  try {
    if (id) sessionSet(PROJECT_KEY, id);
    else sessionDel(PROJECT_KEY);
  } catch {
    /* ignore */
  }
  try {
    localStorage.removeItem(PROJECT_KEY);
  } catch {
    /* ignore */
  }
}

/** Headers every server-mode request must carry (merged by transport). */
export function authHeaders(): Record<string, string> {
  if (!SERVER_MODE) return {};
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const project = getProjectId();
  if (project) headers["X-Project-Id"] = project;
  return headers;
}

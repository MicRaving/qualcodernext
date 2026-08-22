/**
 * Server-session storage (SERVER_PLAN.md §6.7).
 *
 * Bearer token + active project id for server mode. localStorage is the
 * storage backend; swapping in a Tauri secure store later only touches
 * this module. In local (desktop) mode nothing here is used.
 */
import { SERVER_MODE } from "@/lib/config";

const TOKEN_KEY = "qc-server-token";
const PROJECT_KEY = "qc-server-project";

export function isServerMode(): boolean {
  return SERVER_MODE;
}

export function getToken(): string | null {
  if (!SERVER_MODE) return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — session lives until reload */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(PROJECT_KEY);
  } catch {
    /* ignore */
  }
}

export function getProjectId(): string | null {
  if (!SERVER_MODE) return null;
  try {
    return localStorage.getItem(PROJECT_KEY);
  } catch {
    return null;
  }
}

export function setProjectId(id: string | null): void {
  try {
    if (id) localStorage.setItem(PROJECT_KEY, id);
    else localStorage.removeItem(PROJECT_KEY);
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

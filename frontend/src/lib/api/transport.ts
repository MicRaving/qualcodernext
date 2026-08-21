/**
 * Transport infrastructure for the QualCoder v4 API client.
 *
 * Base-URL resolution, error types, fetch wrappers, and URL helpers.
 * This module has NO dependencies on types.ts or endpoints.ts.
 */

import {
  DEV_API_BASE,
  PORT_POLL_INTERVAL_MS,
  PORT_POLL_MAX_ATTEMPTS,
  REQUEST_TIMEOUT_MS,
  SOURCE_TIMEOUT_MS,
} from "@/lib/config";

let resolvedBase: string | null = null;
let basePromise: Promise<string> | null = null;

const DEV_FALLBACK = DEV_API_BASE;

function resolveBase(): Promise<string> {
  if (!basePromise) {
    basePromise = (async () => {
      if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
        try {
          const core = await import("@tauri-apps/api/core");
          // The embedded backend takes a few seconds to start; its port file
          // appears early (written before the heavy imports), so poll fast
          // instead of sitting through a fixed delay.
          for (let i = 0; i < PORT_POLL_MAX_ATTEMPTS; i++) {
            try {
              const port = await core.invoke<number>("backend_port");
              if (typeof port === "number" && port > 0) {
                return `http://127.0.0.1:${port}/api/v1`;
              }
            } catch {
              /* not in the Tauri shell — use the dev default */
            }
            await new Promise((r) => setTimeout(r, PORT_POLL_INTERVAL_MS));
          }
        } catch {
          /* fall through to the dev default */
        }
      }
      return DEV_FALLBACK;
    })();
  }
  return basePromise;
}

/** Kick off base-URL resolution at startup (sync callers then see the port). */
export function initApiBase(): Promise<string> {
  return resolveBase().then((base) => {
    resolvedBase = base;
    return base;
  });
}

/** Synchronous base URL for URL helpers (img/video/audio sources). */
export function apiBaseSync(): string {
  return resolvedBase ?? DEV_FALLBACK;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Path portion of a Response URL ("" when unavailable). */
function urlPathOf(res: Response): string {
  try {
    return new URL(res.url).pathname;
  } catch {
    return "";
  }
}

/** Build an ApiError from a non-ok Response, reading the backend's JSON
 *  `detail` (FastAPI) so the real message — never a bare "Failed to
 *  fetch" — reaches the UI. */
async function apiErrorFrom(res: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await res.json()).detail;
  } catch {
    /* non-JSON error body */
  }
  const where = urlPathOf(res) || "request";
  const suffix =
    typeof detail === "string"
      ? `: ${detail}`
      : detail !== undefined
        ? `: ${JSON.stringify(detail)}`
        : "";
  return new ApiError(res.status, `API error ${res.status} on ${where}${suffix}`, detail);
}

/** Transport-level failures (TypeError "Failed to fetch", abort) are the
 *  only errors worth retrying after re-resolving the API base. HTTP error
 *  responses are definitive — their bodies are parsed into ApiError. */
function isNetworkError(e: unknown): boolean {
  if (e instanceof TypeError) return true;
  return e instanceof DOMException && e.name === "AbortError";
}

/** Fetch with an AbortController timeout (no request ever hangs forever). */
export function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() =>
    window.clearTimeout(timer),
  );
}

/** Raw-file fetch shared by the coders (PDF bytes, HTML snapshots, full
 *  images, thumbnails). The URL is built from the RESOLVED base (`await
 *  resolveBase()` — cheap once the App boot gate settled) and a
 *  transport-level failure (backend still booting, restarted on a new
 *  ephemeral port…) drops the cached base, re-resolves it afresh and
 *  retries exactly once — mirroring `request()`. A non-ok HTTP response
 *  becomes an `ApiError` carrying the backend's JSON `detail` (FastAPI 500s
 *  were previously masked as bare "Failed to fetch" when CORS headers were
 *  missing). */
async function fetchSourceBytes(
  buildUrl: (base: string) => string,
  timeoutMs: number,
): Promise<Response> {
  const attempt = async (): Promise<Response> => {
    const base = await resolveBase();
    resolvedBase = base;
    const res = await fetchWithTimeout(buildUrl(base), undefined, timeoutMs);
    if (!res.ok) throw await apiErrorFrom(res);
    return res;
  };
  try {
    return await attempt();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    basePromise = null;
    resolvedBase = null;
    await new Promise((r) => setTimeout(r, 1000));
    try {
      return await attempt();
    } catch (retryErr) {
      if (retryErr instanceof ApiError) throw retryErr;
      if (isNetworkError(retryErr)) {
        throw new ApiError(
          0,
          `Backend unreachable — ${retryErr instanceof Error ? retryErr.message : "network error"}`,
        );
      }
      throw retryErr;
    }
  }
}

/** Raw bytes of a source file (PDF pages, HTML snapshots, full images).
 *  Resolves to the Response on success; a non-ok HTTP response throws an
 *  `ApiError` whose message carries the backend's `detail`. */
export function fetchSourceFile(sourceId: number, timeoutMs = SOURCE_TIMEOUT_MS): Promise<Response> {
  return fetchSourceBytes((base) => `${base}/sources/${sourceId}/file`, timeoutMs);
}

/** Drop the cached base URL so the next `initApiBase()` resolves it afresh.
 *  Used by callers that cannot go through the fetch helpers (media elements
 *  stream from a raw URL) when the backend restarted on a new port. */
export function invalidateApiBase(): void {
  basePromise = null;
  resolvedBase = null;
}

export async function request<T>(path: string, init?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const parse = async (res: Response): Promise<T> => {
    if (!res.ok) throw await apiErrorFrom(res);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  };
  const attempt = async (): Promise<T> => {
    const base = await resolveBase();
    resolvedBase = base;
    const res = await fetchWithTimeout(`${base}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    }, timeoutMs);
    return parse(res);
  };
  try {
    return await attempt();
  } catch (err) {
    if (!isNetworkError(err)) throw err;
    // Network-level failure (the packaged backend died or its port changed,
    // the dev backend was restarted…): drop the cached base URL, resolve it
    // afresh and retry exactly once before giving up.
    basePromise = null;
    resolvedBase = null;
    try {
      return await attempt();
    } catch (retryErr) {
      if (retryErr instanceof ApiError) throw retryErr;
      if (isNetworkError(retryErr)) {
        // Both attempts failed at the transport level — never surface the
        // raw "Failed to fetch" (it reads as a broken app); say what happened.
        throw new ApiError(
          0,
          `Backend unreachable — ${retryErr instanceof Error ? retryErr.message : "network error"}`,
        );
      }
      throw retryErr;
    }
  }
}

/** URL to the raw source file bytes (used as img/video/pdf src). */
export function sourceFileUrl(sourceId: number): string {
  return `${apiBaseSync()}/sources/${sourceId}/file`;
}

/** Shared JSON fetch for endpoints consumed outside the `api` object (QTT,
 *  creative, stats, code-sets, links, dictionaries, …). Resolves the base
 *  URL, applies the JSON content-type unless the body is FormData,
 *  normalizes non-2xx responses into `ApiError` (with the backend's
 *  `detail`) and retries ONCE on transport-level failure — the packaged
 *  backend may have restarted on a new port. This is the single home of the
 *  pattern feature modules used to copy around; new local clients should
 *  call it instead of re-implementing it. */
export async function localRequest<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const doFetch = async (): Promise<T> => {
    const base = await initApiBase();
    const headers =
      init.body instanceof FormData ? undefined : { "Content-Type": "application/json" };
    const res = await fetchWithTimeout(`${base}${path}`, { headers, ...init }, timeoutMs);
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    // Network-level failure (the packaged backend restarted): retry once so
    // the base URL is resolved afresh.
    return doFetch();
  }
}

/** Same contract as {@link localRequest} for binary (Blob) responses. */
export async function localRequestBlob(
  path: string,
  init: RequestInit = {},
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<Blob> {
  const doFetch = async (): Promise<Blob> => {
    const base = await initApiBase();
    const headers =
      init.body instanceof FormData ? undefined : { "Content-Type": "application/json" };
    const res = await fetchWithTimeout(`${base}${path}`, { headers, ...init }, timeoutMs);
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = (await res.json()).detail;
      } catch {
        /* non-JSON error body */
      }
      const suffix = typeof detail === "string" && detail ? `: ${detail}` : "";
      throw new ApiError(res.status, `API error ${res.status} on ${path}${suffix}`, detail);
    }
    return res.blob();
  };
  try {
    return await doFetch();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    return doFetch();
  }
}

/** URL to an R artifact (PNG/CSV written by an R job into the exchange dir). */
export function rArtifactUrl(name: string): string {
  return `${apiBaseSync()}/r/artifacts/${encodeURIComponent(name)}`;
}

export async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw await apiErrorFrom(res);
  return (await res.json()) as T;
}
